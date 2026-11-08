"""Offline single-file HTML report (FR-004, D-06, REQ-REP-003). stdlib only: ``string.Template`` skeleton, inline CSS,
native ``<details>`` collapsing, no JavaScript, no external fonts, images, styles or scripts.

Every untrusted string (code excerpts, messages, paths, AI or log text) goes through ``esc``: control characters are made
visible by sanitize_text, then HTML-escaped with quotes. The only non-fragment links are evidence anchors whose URL is
https and comes from the model. The template is embedded here (not a data file) so the wheel needs no package-data
entry. Pure function of the model."""

import html as _html
from string import Template

from odooflux.reporting.options import sanitize_text
from odooflux.reporting.terminal.ansi import LAYER_NAMES, num

CSS = """
body{font-family:system-ui,sans-serif;margin:0;color:#1b1f23;background:#fff;line-height:1.45}
header,main,footer,nav{padding:.6rem 1.2rem}
header{background:#f3f4f6;border-bottom:1px solid #d0d7de}
nav a{margin-right:1rem}
h1{font-size:1.3rem;margin:.2rem 0}
h2{font-size:1.1rem;border-bottom:1px solid #d0d7de;padding-bottom:.2rem}
table{border-collapse:collapse;margin:.4rem 0}
th,td{border:1px solid #d0d7de;padding:.2rem .5rem;text-align:left;vertical-align:top}
code,pre{font-family:ui-monospace,monospace;font-size:.9em;white-space:pre-wrap;word-break:break-word}
details{border:1px solid #d0d7de;border-radius:4px;margin:.5rem 0;padding:.3rem .6rem}
summary{cursor:pointer;font-weight:600}
.badge{border:1px solid;border-radius:3px;padding:0 .35rem;font-weight:700}
.status-VERIFIED_SUCCESS,.status-INSTALL_VERIFIED,.pass{color:#116329}
.status-STATIC_VALIDATED{color:#0550ae}
.status-NEEDS_REVIEW,.unavailable{color:#8a4600}
.status-FAILED,.status-BLOCKED,.fail{color:#a40e26}
.skipped{color:#57606a}
.provisional{border:2px solid #8a4600;background:#fff8c5;padding:.5rem .8rem;margin:.5rem 1.2rem;font-weight:600}
.tiles span.tile{display:inline-block;border:1px solid #d0d7de;border-radius:4px;padding:.3rem .7rem;margin:.2rem}
"""

PAGE = Template("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>OdooFlux report $run_id</title>
<style>$css</style>
</head>
<body>
<header>
<h1>OdooFlux $tool_version</h1>
<p>Run <code>$run_id</code> &middot; source $source &rarr; target $target &middot; mode $mode</p>
$overall
</header>
$provisional
<nav>
<a href="#summary">Summary</a><a href="#plan">Plan</a><a href="#modules">Modules</a><a href="#rejected">Rejected edits</a><a href="#scope">Verification scope</a><a href="#ai">AI usage</a><a href="#recovery">Recovery</a>
</nav>
<main>
$sections
</main>
<footer>
<p>schema_version $schema_version &middot; generated offline from the JSON report model; this file loads nothing from the network.</p>
</footer>
</body>
</html>
""")


def esc(value) -> str:
    return _html.escape(sanitize_text(value), quote=True)


def _metric(name: str, value) -> str:
    return f'<span data-metric="{name}">{int(value)}</span>'


def _evidence(item) -> str:
    if isinstance(item, dict):
        url = str(item.get("url", ""))
        if url.startswith("https://"):
            return f'<a class="evidence" rel="noopener noreferrer" href="{esc(url)}">{esc(item.get("id", ""))}</a>'
        return f"<code>{esc(item.get('id', ''))}</code>"
    return f"<code>{esc(item)}</code>"


def _outcome(layer: dict) -> str:
    cls = layer["outcome"].lower()
    reason = f" ({esc(layer['reason'])})" if layer.get("reason") else ""
    return f'<span class="outcome {cls}">{layer["outcome"]}</span>{reason}'


def _summary(report: dict) -> str:
    s, mods = report["summary"], report["modules"]
    st, op, tot = s["findings_by_status"], s["open_findings"], s["findings"]
    tiles = "".join(f'<span class="tile status-{k}">{esc(k)}: {v}</span>' for k, v in sorted(s["modules_by_status"].items()))
    return f"""<section id="summary">
<h2>Summary</h2>
<p class="tiles">{tiles}</p>
<table>
<tr><th>Modules</th><td>{_metric("modules", len(mods))}</td></tr>
<tr><th>Findings</th><td>{_metric("findings", sum(tot.values()))}</td></tr>
<tr><th>Open (open and needs review)</th><td>{_metric("open", sum(op.values()))}</td></tr>
<tr><th>Open critical</th><td>{_metric("open_critical", op["critical"])}</td></tr>
<tr><th>Open warning</th><td>{_metric("open_warning", op["warning"])}</td></tr>
<tr><th>Open info</th><td>{_metric("open_info", op["info"])}</td></tr>
<tr><th>Fixed</th><td>{_metric("fixed", st["fixed"])}</td></tr>
<tr><th>Rejected</th><td>{_metric("rejected", st["rejected"])}</td></tr>
<tr><th>Needs review</th><td>{_metric("needs_review", st["needs_review"])}</td></tr>
<tr><th>Edits applied / rejected</th><td>{s["edits"]["applied"]} / {s["edits"]["rejected"]}</td></tr>
<tr><th>Files written</th><td>{s["files_written"]}</td></tr>
</table>
</section>"""


def _plan(report: dict) -> str:
    run = report["run"]
    steps = "".join(f"<li><code>{esc(s)}</code></li>" for s in run["steps"]) or "<li>(none)</li>"
    reasons = "".join(f"<li>{esc(r)}</li>" for r in run.get("plan_reasons", []))
    blocked = f"<p>Plan status BLOCKED:</p><ul>{reasons}</ul>" if run["plan_status"] == "BLOCKED" else ""
    return f'<section id="plan">\n<h2>Plan</h2>\n<p>Status: {esc(run["plan_status"])}</p>\n<ol>{steps}</ol>\n{blocked}\n</section>'


def _module(index: int, m: dict) -> str:
    open_c = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
    for f in m["findings"]:
        if f["status"] in ("OPEN", "NEEDS_REVIEW"):
            open_c[f["severity"]] += 1
    head = (f'<summary><span class="badge status-{esc(m["status"])}">{esc(m["status"])}</span> {esc(m["name"])} '
            f'&middot; open C/W/I {open_c["CRITICAL"]}/{open_c["WARNING"]}/{open_c["INFO"]}</summary>')
    reasons = ("<p>Reasons: " + ", ".join(f"<code>{esc(r)}</code>" for r in m["status_reasons"]) + "</p>"
               if m["status_reasons"] else "")
    layers = "".join(f"<tr><td>{esc(LAYER_NAMES[int(k[1])])}</td><td>{_outcome(v)}</td></tr>"
                     for k, v in sorted(m["layers"].items()))
    by_file: dict = {}
    for f in m["findings"]:
        by_file.setdefault(f["path"], []).append(f)
    files = ""
    for path, items in by_file.items():
        rows = ""
        for f in items:
            label = f["severity"] if f["status"] in ("OPEN", "NEEDS_REVIEW") else f["status"]
            extra = ""
            if f.get("suggestion") and f["status"] != "FIXED":
                extra += f"<br>Action: {esc(f['suggestion'])}"
            if f.get("rejection_reason"):
                extra += f"<br>Rejected: {esc(f['rejection_reason'])}"
            ev = " ".join(_evidence(e) for e in f.get("evidence", []))
            if ev and f["status"] != "FIXED":
                extra += f"<br>Evidence: {ev}"
            loc = f"L{f['line']}" + (f":{f['column']}" if f.get("column") else "")
            rows += (f"<tr><td><strong>{esc(label)}</strong></td><td>{esc(loc)}</td><td><code>{esc(f['rule_id'])}</code></td>"
                     f"<td>{esc(f['status'])}</td><td>{esc(f['message'])}{extra}</td></tr>")
        files += (f"<h3><code>{esc(path)}</code></h3><table><thead><tr><th>Severity</th><th>Location</th><th>Rule</th>"
                  f"<th>Status</th><th>Message</th></tr></thead><tbody>{rows}</tbody></table>")
    edits = "".join(f"<li><code>{esc(e['path'])}</code>: {len(e['spans'])} span(s)"
                    + (f" &rarr; <code>{esc(e['dest'])}</code>" if e["dest"] != e["path"] else "") + "</li>"
                    for e in m["edits"])
    rejected = "".join(f"<li>{esc(r if isinstance(r, str) else str(r))}</li>" for r in m["rejections"])
    runtime = ""
    if m.get("runtime"):
        rt = m["runtime"]
        errors = "".join(f"<li>{esc(e if isinstance(e, str) else str(e))}</li>" for e in rt["errors"])
        runtime = (f"<h3>Runtime</h3><p>image <code>{esc(rt['image'])}</code> digest <code>{esc(rt['digest'])}</code> "
                   f"logs <code>{esc(rt['logs_path'])}</code></p><ul>{errors}</ul>")
    behavior = ""
    if m.get("behavior"):
        rows = "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in sorted(m["behavior"]["summary"].items()))
        behavior = f"<h3>Behaviour</h3><table>{rows}</table>"
    return (f'<details id="module-{index}">{head}{reasons}<h3>Validation layers</h3><table>{layers}</table>'
            f'{files or "<p>No findings.</p>"}<h3>Edits</h3><ul>{edits or "<li>none kept</li>"}</ul>'
            f'{("<h3>Rejected edits</h3><ul>" + rejected + "</ul>") if rejected else ""}{runtime}{behavior}</details>')


def _modules(report: dict) -> str:
    return '<section id="modules">\n<h2>Modules</h2>\n' + "\n".join(
        _module(i, m) for i, m in enumerate(report["modules"], 1)) + "\n</section>"


def _rejected(report: dict) -> str:
    items = [(m["name"], r) for m in report["modules"] for r in m["rejections"]]
    body = ("<ul>" + "".join(f"<li><code>{esc(n)}</code>: {esc(r if isinstance(r, str) else str(r))} "
                             f"&mdash; file left unchanged</li>" for n, r in items) + "</ul>") if items else "<p>None.</p>"
    return f'<section id="rejected">\n<h2>Rejected edits ({len(items)})</h2>\n{body}\n</section>'


def _scope(report: dict) -> str:
    scope = report["verification_scope"]
    ran = scope["layers_run"]
    reasons = scope.get("reasons", {})
    lines = [f"<li>Ran: {esc(', '.join(LAYER_NAMES[n] for n in ran) if ran else 'nothing')}</li>"]
    not_run = sorted(set(scope.get("layers_skipped", [])) | {n for n in scope["layers_unavailable"] if n in (4, 5)})
    if not_run:
        lines.append("<li>Not run: " + esc(", ".join(f"{LAYER_NAMES[n]} ({reasons.get(f'L{n}', 'not_run')})"
                                                      for n in not_run)) + "</li>")
    outcomes = scope.get("layer_outcomes", {})
    unavailable = sorted({n for n in scope["layers_unavailable"] if n not in (4, 5)}
                         | {n for n in range(1, 6) if outcomes.get(f"L{n}", {}).get("UNAVAILABLE") and n not in not_run})
    if unavailable:
        lines.append("<li>Unavailable: " + esc(", ".join(LAYER_NAMES[n] for n in unavailable)) + "</li>")
    for n in range(1, 6):
        counts = outcomes.get(f"L{n}")
        if counts:
            lines.append(f"<li>L{n}: " + esc(", ".join(f"{k} {v}" for k, v in counts.items() if v)) + " module(s)</li>")
    for limit in scope.get("limits", []):
        lines.append(f"<li>Limit: {esc(limit)}</li>")
    missing = [n for n in (4, 5) if n not in ran]
    why = ""
    if missing:
        names = " and ".join({4: "installation (L4)", 5: "behaviour (L5)"}[n] for n in missing)
        reason = "; ".join(dict.fromkeys(reasons.get(f"L{n}", "not_run") for n in missing))
        why = f"<p><strong>Why not verified:</strong> {names} were not run ({esc(reason)}). Business behaviour is unverified.</p>"
    return f'<section id="scope">\n<h2>Verification scope</h2>\n<ul>{"".join(lines)}</ul>\n{why}\n</section>'


def _ai(report: dict) -> str:
    ai = report["ai_usage"]
    if not ai["enabled"]:
        return '<section id="ai">\n<h2>AI usage</h2>\n<p>Not used in this run.</p>\n</section>'
    consent = {True: "consent given", False: "consent NOT given", None: "consent not recorded"}[ai.get("consent")]
    rows = "".join(
        f"<tr><td>{esc(p['name'] + '/' + p['model'])}</td><td>{num(p['requests'])}</td><td>{num(p.get('input_tokens', 0))}</td>"
        f"<td>{num(p.get('output_tokens', 0))}</td><td>{num(p.get('cached_tokens', 0))}</td>"
        f"<td>{'not configured' if p.get('cost') is None else esc(p['cost'])}</td></tr>" for p in ai["providers"])
    events = "".join(f"<li>{esc(e)}</li>" for e in ai.get("budget_events", []))
    return (f'<section id="ai">\n<h2>AI usage</h2>\n<p>Enabled, {consent}.</p>\n<table><thead><tr><th>provider/model</th>'
            f"<th>requests</th><th>in tokens</th><th>out tokens</th><th>cached</th><th>cost</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>\n<ul>{events}</ul>\n</section>")


def _recovery(report: dict) -> str:
    rec, run = report["recovery"], report["run"]
    if run["mode"] == "fix":
        back = (f"<li>Roll back: <code>{esc(rec['rollback_cmd'])}</code></li>" if rec["reversible"]
                else "<li>Roll back: NOT reversible (--no-backup): no pre-run backup was taken</li>")
    else:
        back = "<li>Roll back: not needed, nothing was written (analyze or dry run)</li>"
    warnings = ("<h3>Warnings</h3><ul>" + "".join(f"<li>{esc(w)}</li>" for w in report.get("warnings", [])) + "</ul>"
                if report.get("warnings") else "")
    return (f'<section id="recovery">\n<h2>Recovery</h2>\n<ul><li>Run log: <code>{esc(rec["run_log"] or "(not recorded)")}</code>'
            f"</li>{back}</ul>\n{warnings}\n</section>")


def render_html(report: dict) -> str:
    run = report["run"]
    provisional = ""
    if report.get("provisional", {}).get("active"):
        labels = "; ".join(esc(label) for label in report["provisional"]["labels"])
        provisional = (f'<div class="provisional">PROVISIONAL RUN: {labels}. Results depend on a provisional validation '
                       f"corpus and are not approved migration truth.</div>")
    s = report["summary"]
    overall = (f"<p>{len(report['modules'])} module(s); open findings "
               f"{sum(s['open_findings'].values())}; fixed {s['findings_by_status']['fixed']}; rejected "
               f"{s['findings_by_status']['rejected']}</p>")
    sections = "\n".join((_summary(report), _plan(report), _modules(report), _rejected(report), _scope(report),
                          _ai(report), _recovery(report)))
    return PAGE.substitute(
        css=CSS, run_id=esc(run["run_id"]), tool_version=esc(run.get("tool_version", "")), source=esc(run["source"]),
        target=esc(run["target"]), mode=esc(run["mode"]), overall=overall, provisional=provisional,
        sections=sections, schema_version=esc(report["schema_version"]))


class HtmlRenderer:
    key = "html"
    contract_version = 1

    def render(self, report: dict, **options) -> str:
        return render_html(report)
