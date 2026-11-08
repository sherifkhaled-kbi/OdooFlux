"""Default terminal renderer: stdlib ANSI, colour and plain modes (FR-003, D-07). Pure function of the model.

Layout is computed on visible text only and colour is applied to finished tokens, so colour and plain output have
identical layout (F-REP-2). All untrusted text goes through sanitize_text (FR-008)."""

from odooflux.reporting.options import RendererOptions, display_width, sanitize_text
from odooflux.reporting.terminal.progress import progress_lines, stage_line

RESET = "\x1b[0m"
STYLES = {"bold": "1", "red": "31", "green": "32", "yellow": "33", "blue": "34", "cyan": "36", "dim": "2"}
STATUS_STYLE = {"VERIFIED_SUCCESS": "green", "INSTALL_VERIFIED": "green", "STATIC_VALIDATED": "cyan",
                "NEEDS_REVIEW": "yellow", "FAILED": "red", "BLOCKED": "red"}
SEVERITY_STYLE = {"CRITICAL": "red", "WARNING": "yellow", "INFO": "blue", "FIXED": "green", "REJECTED": "red"}
LAYER_NAMES = {1: "L1 syntax", 2: "L2 static re-scan", 3: "L3 dependency integrity", 4: "L4 runtime install",
               5: "L5 behaviour"}
SEVERITY_RANK = {"INFO": 1, "WARNING": 2, "CRITICAL": 3}
STATUS_W = 16
TABLE_MIN_COLUMNS = 110


def num(n) -> str:
    """Locale-independent number: thousands separated by a space."""
    return f"{int(n):,}".replace(",", " ")


def wrap(text: str, width: int, first: str = "", rest: str = None) -> list:
    """Greedy wrap on display width; runs of spaces are kept inside a line, tokens longer than the line are
    hard-broken, trailing spaces are dropped. Every returned line fits *width*."""
    rest = first if rest is None else rest
    lines: list = []
    state = {"indent": first, "cur": None}

    def avail() -> int:
        return max(width - display_width(state["indent"]), 4)

    def flush() -> None:
        lines.append((state["indent"] + (state["cur"] or "")).rstrip())
        state["indent"], state["cur"] = rest, None

    for word in text.split(" "):
        while display_width(word) > avail():
            if state["cur"] is not None:
                flush()
            take, acc = "", 0
            for ch in word:
                w = display_width(ch)
                if acc + w > avail():
                    break
                take, acc = take + ch, acc + w
            state["cur"] = take
            flush()
            word = word[len(take):]
        cur = state["cur"]
        if cur is not None and word and display_width(cur) + 1 + display_width(word) > avail():
            flush()
            cur = None
        state["cur"] = word if cur is None else cur + " " + word
    if state["cur"] is not None or not lines:
        flush()
    return lines


class _Painter:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __call__(self, text: str, *styles: str) -> str:
        if not self.enabled or not styles or not text:
            return text
        return "\x1b[" + ";".join(STYLES[s] for s in styles) + "m" + text + RESET


def _pad(text: str, width: int, painted: str = None) -> str:
    return (painted if painted is not None else text) + " " * max(width - display_width(text), 0)


def _evidence_text(item) -> str:
    if isinstance(item, dict):
        return sanitize_text(f"{item.get('id', '')} {item.get('url', '')}".strip())
    return sanitize_text(item)


def _finding_label(f: dict) -> str:
    return f["severity"] if f["status"] in ("OPEN", "NEEDS_REVIEW") else f["status"]


def _loc(f: dict) -> str:
    return f"L{f['line']}" + (f":{f['column']}" if f.get("column") else "")


def _layers_text(module: dict, with_reason: bool = False) -> str:
    parts = []
    for key, layer in sorted(module["layers"].items()):
        text = f"{key} {layer['outcome']}"
        if with_reason and layer["outcome"] != "PASS" and layer.get("reason"):
            text += f" ({sanitize_text(layer['reason'])})"
        parts.append(text)
    return " ".join(parts)


def _open_cwi(module: dict) -> str:
    counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
    for f in module["findings"]:
        if f["status"] in ("OPEN", "NEEDS_REVIEW"):
            counts[f["severity"]] += 1
    return f"{counts['CRITICAL']}/{counts['WARNING']}/{counts['INFO']}"


def _count(module: dict, status: str) -> int:
    return sum(1 for f in module["findings"] if f["status"] == status)


def render_terminal(report: dict, options: RendererOptions = None, *, is_tty: bool = False) -> str:
    options = options or RendererOptions()
    paint = _Painter(options.use_color(is_tty))
    W = options.columns
    out: list = []
    summary = report["summary"]
    modules = report["modules"]

    def emit(*lines):
        out.extend(lines)

    def section(title: str, extra: str = ""):
        emit("")
        emit(paint(title, "bold") + extra)

    run = report["run"]
    head = (f"OdooFlux  run {sanitize_text(run['run_id'])}  source {sanitize_text(run['source'])} -> target "
            f"{sanitize_text(run['target'])}  mode: {run['mode']}")
    emit(*wrap(head, W, "", "  "))
    if report.get("provisional", {}).get("active"):
        for i, label in enumerate(report["provisional"]["labels"] or [""]):
            emit(*[paint(line, "bold", "yellow") for line in wrap(
                sanitize_text(label), W, "PROVISIONAL RUN: " if i == 0 else "  ", "  ")])
        emit(*wrap("Results depend on a provisional validation corpus and are not approved migration truth.", W, "  "))
    if report.get("knowledge_release"):
        release = report["knowledge_release"]
        emit(*wrap(f"Knowledge release {sanitize_text(release['release_id'])}  digest "
                   f"{sanitize_text(release['digest'] or 'unavailable')}", W, "", "  "))
    emit(*wrap(f"Plan  {' -> '.join(sanitize_text(s) for s in run['steps']) or '(none)'}   status: "
               f"{run['plan_status']}" + (f" ({'; '.join(sanitize_text(r) for r in run['plan_reasons'])})"
                                          if run.get("plan_reasons") else ""), W, "", "  "))
    emit(*wrap("Stages: " + stage_line(), W, "", "  "))

    if options.verbose:
        section("PROGRESS")
        for line in progress_lines(report):
            emit(*wrap(line, W, "  ", "      "))

    # MODULE RESULTS ---------------------------------------------------------------------------------------
    section("MODULE RESULTS")
    layers_w = max((display_width(_layers_text(m)) for m in modules), default=0)
    fixed_w = rej_w = 8
    name_budget = W - (1 + STATUS_W + 1 + 10 + 1 + 5 + 1 + rej_w + 1 + layers_w)
    table = modules and name_budget >= 12 and W >= TABLE_MIN_COLUMNS
    if table:
        name_w = min(max(display_width(sanitize_text(m["name"])) for m in modules), name_budget)
        emit(" " + _pad("Status", STATUS_W) + " " + _pad("Module", name_w) + " " + _pad("Open C/W/I", 10) + " "
             + _pad("Fixed", 5) + " " + _pad("Rejected", rej_w) + " Layers")
        for m in modules:
            name_lines = wrap(sanitize_text(m["name"]), name_w)
            first = (" " + _pad(m["status"], STATUS_W, paint(m["status"], STATUS_STYLE[m["status"]], "bold")) + " "
                     + _pad(name_lines[0], name_w) + " " + _pad(_open_cwi(m), 10) + " "
                     + _pad(str(_count(m, "FIXED")), 5) + " " + _pad(str(_count(m, "REJECTED")), rej_w) + " "
                     + _layers_text(m))
            emit(first)
            for extra in name_lines[1:]:
                emit(" " + " " * STATUS_W + " " + extra)
    else:
        for m in modules:
            emit(" " + paint(m["status"], STATUS_STYLE[m["status"]], "bold") + "  " + sanitize_text(m["name"]))
            emit(f"   open C/W/I {_open_cwi(m)}   fixed {_count(m, 'FIXED')}   rejected {_count(m, 'REJECTED')}")
            emit(*wrap("layers: " + _layers_text(m), W, "   ", "           "))
    for m in modules:
        if m["status_reasons"]:
            emit(*wrap(f"{sanitize_text(m['name'])}: " + ", ".join(sanitize_text(r) for r in m["status_reasons"]),
                       W, "  Reasons  ", "           "))
        if options.verbose:
            emit(*wrap(f"{sanitize_text(m['name'])}: " + _layers_text(m, True), W, "  Layers   ", "           "))

    # FINDINGS ---------------------------------------------------------------------------------------------
    section("FINDINGS", "" if options.show_fixed else "  (open and needs-review; --show-fixed lists fixed)")
    shown_any = False
    for m in modules:
        by_file: dict = {}
        for f in m["findings"]:
            if f["status"] == "FIXED" and not options.show_fixed:
                continue
            if SEVERITY_RANK[f["severity"]] < SEVERITY_RANK[options.min_severity]:
                continue
            by_file.setdefault(f["path"], []).append(f)
        for path, items in by_file.items():
            shown_any = True
            emit(*wrap(sanitize_text(f"{m['name']}/{path}"), W, "", "  "))
            for f in items[:options.max_findings_per_file]:
                label = _finding_label(f)
                status = f" [{f['status']}]" if f["status"] != "FIXED" else ""
                prefix_plain = f"{label:<8} {_loc(f)}  {sanitize_text(f['rule_id'])}{status}"
                lines = wrap(prefix_plain, W, "  ", "      ")
                lines[0] = lines[0].replace(label, paint(label, SEVERITY_STYLE.get(label, "bold"), "bold"), 1)
                emit(*lines)
                emit(*wrap(sanitize_text(f["message"]), W, "           "))
                if f["status"] != "FIXED":
                    if f.get("suggestion"):
                        emit(*wrap("Action: " + sanitize_text(f["suggestion"]), W, "           ", "                   "))
                    if f.get("rejection_reason"):
                        emit(*wrap("Rejected: " + sanitize_text(f["rejection_reason"]), W, "           ",
                                   "                    "))
                    for ev in f.get("evidence", []):
                        emit(*wrap("Evidence: " + _evidence_text(ev), W, "           ", "                    "))
            hidden = len(items) - options.max_findings_per_file
            if hidden > 0:
                emit(*wrap(f"... {hidden} more finding(s) not shown (see the JSON or HTML report for all)", W, "  "))
    if not shown_any:
        emit("  none to show")

    # REJECTED EDITS ---------------------------------------------------------------------------------------
    rejected = [(m["name"], r) for m in modules for r in m["rejections"]]
    if rejected:
        section(f"REJECTED EDITS ({len(rejected)})")
        for name, reason in rejected:
            text = reason if isinstance(reason, str) else str(reason)
            emit(*wrap(f"{sanitize_text(name)}: reason: {sanitize_text(text)} - file left unchanged", W, "  ", "      "))
    else:
        section("REJECTED EDITS: none")

    # VERIFICATION SCOPE -----------------------------------------------------------------------------------
    scope = report["verification_scope"]
    section("VERIFICATION SCOPE")
    ran = scope["layers_run"]
    emit(*wrap("Ran: " + (", ".join(LAYER_NAMES[n] for n in ran) if ran else "nothing"), W, "  ", "      "))
    reasons = scope.get("reasons", {})
    not_run = sorted(set(scope.get("layers_skipped", [])) | {n for n in scope["layers_unavailable"] if n in (4, 5)})
    if not_run:
        emit(*wrap("Not run: " + ", ".join(f"{LAYER_NAMES[n]} ({sanitize_text(reasons.get(f'L{n}', 'not_run'))})"
                                           for n in not_run), W, "  ", "      "))
    unavailable = [n for n in scope["layers_unavailable"] if n not in (4, 5)]
    outcomes = scope.get("layer_outcomes", {})
    for n in range(1, 6):
        counts = outcomes.get(f"L{n}", {})
        if counts.get("UNAVAILABLE") and n not in not_run:
            unavailable.append(n)
    if unavailable:
        emit(*wrap("Unavailable: " + ", ".join(LAYER_NAMES[n] for n in sorted(set(unavailable))), W, "  ", "      "))
    for n in range(1, 6):
        counts = outcomes.get(f"L{n}")
        if counts:
            emit(*wrap(f"L{n}: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v) + " module(s)",
                       W, "    "))
    for limit in scope.get("limits", []):
        emit(*wrap("Limit: " + sanitize_text(limit), W, "  ", "         "))
    missing = [n for n in (4, 5) if n not in ran]
    if missing:
        names = " and ".join({4: "installation (L4)", 5: "behaviour (L5)"}[n] for n in missing)
        why = "; ".join(dict.fromkeys(sanitize_text(reasons.get(f"L{n}", "not_run")) for n in missing))
        emit(*wrap(f"Why not verified: {names} were not run ({why}). Business behaviour is unverified.",
                   W, "  ", "      "))

    # RUNTIME ----------------------------------------------------------------------------------------------
    runtimes = [m for m in modules if m.get("runtime") or m.get("behavior")]
    if runtimes:
        section("RUNTIME AND BEHAVIOUR")
        for m in runtimes:
            rt = m.get("runtime")
            if rt:
                emit(*wrap(f"{sanitize_text(m['name'])}: image {sanitize_text(rt['image'])} digest "
                           f"{sanitize_text(rt['digest'])} errors {len(rt['errors'])}", W, "  ", "      "))
            bh = m.get("behavior")
            if bh:
                emit(*wrap(f"{sanitize_text(m['name'])}: behaviour " + ", ".join(
                    f"{k} {v}" for k, v in sorted(bh["summary"].items())), W, "  ", "      "))

    # AI USAGE ---------------------------------------------------------------------------------------------
    ai = report["ai_usage"]
    if not ai["enabled"]:
        section("AI USAGE  not used in this run")
    else:
        consent = {True: "consent given", False: "consent NOT given", None: "consent not recorded"}[ai.get("consent")]
        section(f"AI USAGE  (enabled, {consent})")
        for p in ai["providers"]:
            label = sanitize_text(f"{p['name']}/{p['model']}")
            cost = "not configured" if p.get("cost") is None else sanitize_text(p["cost"])
            if W >= 80:
                emit(f"  {label:<30} requests {num(p['requests']):>6}  in {num(p.get('input_tokens', 0)):>8}  "
                     f"out {num(p.get('output_tokens', 0)):>7}  cached {num(p.get('cached_tokens', 0)):>7}  cost {cost}"
                     if W >= 120 else f"  {label}")
                if W < 120:
                    emit(*wrap(f"requests {num(p['requests'])}, in {num(p.get('input_tokens', 0))}, out "
                               f"{num(p.get('output_tokens', 0))}, cached {num(p.get('cached_tokens', 0))}, "
                               f"cost {cost}", W, "      "))
            else:
                emit(*wrap(f"{label}: requests {num(p['requests'])}, in {num(p.get('input_tokens', 0))}, out "
                           f"{num(p.get('output_tokens', 0))}, cost {cost}", W, "  ", "      "))
        for event in ai.get("budget_events", []):
            emit(*wrap("budget event: " + sanitize_text(event), W, "  ", "      "))

    # RECOVERY ---------------------------------------------------------------------------------------------
    rec = report["recovery"]
    section("RECOVERY")
    emit(*wrap(f"Run log:   {sanitize_text(rec['run_log']) or '(not recorded)'}", W, "  ", "      "))
    if run["mode"] == "fix":
        if rec["reversible"]:
            emit(*wrap(f"Roll back: {sanitize_text(rec['rollback_cmd'])}", W, "  ", "      "))
        else:
            emit(*wrap("Roll back: NOT reversible (--no-backup): no pre-run backup was taken", W, "  ", "      "))
    else:
        emit(*wrap("Roll back: not needed, nothing was written (analyze or dry run)", W, "  ", "      "))
    if report.get("warnings"):
        section("WARNINGS")
        for w in report["warnings"]:
            emit(*wrap(sanitize_text(w), W, "  ", "      "))

    # TOTALS -----------------------------------------------------------------------------------------------
    st, op, tot = summary["findings_by_status"], summary["open_findings"], summary["findings"]
    emit("")
    emit(*wrap(
        f"TOTALS modules={len(modules)} findings={sum(tot.values())} open={sum(op.values())} "
        f"(critical={op['critical']} warning={op['warning']} info={op['info']}) fixed={st['fixed']} "
        f"rejected={st['rejected']} needs_review={st['needs_review']}", W, "", "  "))
    text = "\n".join(out) + "\n"
    return text


class TerminalRenderer:
    """Registry key ``terminal``. Options: RendererOptions fields, plus ``ui`` (auto|ansi|rich), ``is_tty`` and
    ``no_color`` (maps to color=never)."""

    key = "terminal"
    contract_version = 1

    def render(self, report: dict, ui: str = "ansi", is_tty: bool = False, no_color: bool = False, **options) -> str:
        from odooflux.reporting.terminal.rich_adapter import render_ui
        if no_color:
            options["color"] = "never"
        text, used = render_ui(report, RendererOptions(**options), ui=ui, is_tty=is_tty)
        if ui == "rich" and used != "rich":
            text = "(rich is not installed: using the built-in terminal renderer)\n" + text
        return text
