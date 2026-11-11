"""Legacy Claude integration, wrapped unchanged (REQ-ARC-004, Principle III). Registered as legacy-anthropic."""

import re
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from odooflux.core.contracts import CONTRACT_VERSION
from odooflux.core.engine.apply import FileEdit
from odooflux.core.engine.rescan import resolved_by_rescan
from odooflux.rules.shared.legacy_rules import (
    Issue, SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO, scan_content)

# CLAUDE AI INTEGRATION
# ─────────────────────────────────────────────

CLAUDE_API_URL    = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL      = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 16384
CLAUDE_MAX_BUNDLE_BYTES = 180_000

_AI_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert Odoo migration engineer specialising in upgrading custom Odoo modules to Odoo {to_version}.

You will receive PYTHON FILES from a single Odoo module that need migration fixes to Odoo {to_version}.
Each file is accompanied by a list of detected issues (line number, category, message, fix hint).

YOUR TASK:
- Fix ONLY the listed issues. Return the complete corrected file content.
- Return a single valid JSON object — nothing else. No markdown fences, no preamble,
  no explanation after the JSON.
- The JSON must have this exact structure:

{{
  "files": {{
    "<filename>": "<complete corrected file content as a string>",
    ...
  }},
  "skipped": ["<filename_if_too_complex>", ...],
  "notes": "optional brief summary"
}}

STRICT RULES — VIOLATIONS WILL BREAK PRODUCTION ODOO INSTANCES:
- NEVER remove any import line or any name from an import statement.
  To fix a broken import path, only rewrite the module name (openerp.* -> odoo.*).
  Keep ALL imported names exactly as they are. Never delete an import line.
- NEVER rename any field defined with fields.Char, fields.Many2one, fields.Integer, etc.
  Field names are stored in the PostgreSQL database. Renaming them destroys existing data.
- NEVER rename any model _name or _inherit string value.
  Strings like 'hr.contract', 'account.move', 'res.partner' must stay exactly as-is.
  They are stored in ir.model, ir.rule, security CSV files — renaming them breaks the DB.
- NEVER remove any method, field definition, class, or variable.
- Preserve original indentation style (tabs vs spaces) and line endings exactly.
- Only fix what is explicitly listed in the issues. Do not refactor unrelated code.
- When migrating old-style (cr, uid, ids, context) methods, keep ALL business logic intact;
  only update the method signature and direct ORM calls (search, write, create, browse).
- When fixing "raise Warning(...)", replace only that raise statement with "raise UserError(...)".
  Also ensure "from odoo.exceptions import UserError" exists in imports (add if missing, never remove).
- When converting _columns/_defaults, preserve the exact same field names and logic.
- String values in the JSON must use proper JSON escaping (\\n for newlines, \\" for quotes, etc.).
- Target Odoo version: {to_version}.
"""


def _get_ai_system_prompt(to_version: int) -> str:
    return _AI_SYSTEM_PROMPT_TEMPLATE.format(to_version=to_version)


def _build_bundle_prompt(file_map: dict, from_version: int, to_version: int = 19) -> str:
    lang_map = {".py": "Python", ".xml": "XML", ".js": "JavaScript",
                ".ts": "TypeScript", ".css": "CSS", ".scss": "SCSS"}
    sections = [
        f"MIGRATION: Odoo v{from_version} → Odoo {to_version}\n"
        f"FILES IN BUNDLE: {len(file_map)} (across all modules)\n"
        f"IMPORTANT: Return keys in 'files' exactly as given below ('module/filename' format).\n"
    ]
    for file_key, (filepath_str, content, issues) in file_map.items():
        fp   = Path(filepath_str)
        lang = lang_map.get(fp.suffix.lower(), "text")
        issue_lines = []
        for idx, iss in enumerate(issues, 1):
            issue_lines.append(
                f"    {idx}. [Line {iss.line}] [{iss.severity}] {iss.category}\n"
                f"       Problem : {iss.message}\n"
                f"       Fix hint: {iss.suggestion}"
            )
        sections.append(
            f"{'='*70}\n"
            f"FILE_KEY: {file_key}\n"
            f"LANGUAGE: {lang}\n"
            f"ISSUES ({len(issues)}):\n"
            + "\n".join(issue_lines)
            + f"\n\nCONTENT:\n{content}\n"
        )
    return "\n".join(sections)


def _call_claude_api(api_key: str, user_message: str, to_version: int = 19, retries: int = 3) -> str:
    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": CLAUDE_MAX_TOKENS,
        "system": _get_ai_system_prompt(to_version),
        "messages": [{"role": "user", "content": user_message}],
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                CLAUDE_API_URL, data=payload, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text_blocks = [
                    b["text"] for b in data.get("content", []) if b.get("type") == "text"
                ]
                return "\n".join(text_blocks)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code in (429, 503, 529) and attempt < retries:
                wait = 2 ** attempt
                print(f"\n          [AI] Rate-limited (HTTP {e.code}), retrying in {wait}s…")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Anthropic API HTTP {e.code}: {body[:400]}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error: {e.reason}") from e
    raise RuntimeError("Anthropic API: max retries exceeded")


def _parse_bundle_response(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
    raw = re.sub(r"\n?```\s*$", "", raw)
    raw = raw.strip()
    brace_start = raw.find("{")
    brace_end   = raw.rfind("}")
    if brace_start == -1 or brace_end == -1:
        raise ValueError("No JSON object found in AI response")
    raw = raw[brace_start: brace_end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse error: {e}") from e
    if "files" not in data or not isinstance(data["files"], dict):
        raise ValueError("Response JSON missing 'files' dict")
    return data


def _ensure_newline(text: str) -> str:
    if text and not text.endswith("\n"):
        return text + "\n"
    return text


def fix_bundle(reports: list, module_paths: list, api_key: str, verbose: bool = False,
               run=None, write_module=None, validate_text=None) -> int:
    to_version   = reports[0].to_version   if reports else 19
    from_version = reports[0].from_version if reports else 14

    file_map: dict     = {}
    skipped_large: list = []
    total_bytes = 0
    all_candidates: list = []

    for report, module_path in zip(reports, module_paths):
        if report.blocked:
            continue
        manual_by_file: dict = {}
        for issue in report.issues:
            if not issue.auto_fixable and not issue.fix_applied:
                manual_by_file.setdefault(issue.file, []).append(issue)
        for filepath_str, issues in manual_by_file.items():
            if Path(filepath_str).suffix.lower() != '.py':
                continue
            non_info = [i for i in issues if i.severity != SEVERITY_INFO]
            if not non_info:
                continue
            crit = sum(1 for i in issues if i.severity == SEVERITY_CRITICAL)
            all_candidates.append((crit, len(issues), filepath_str, issues, report, module_path))

    if not all_candidates:
        print("  [AI] No manual-fix issues remaining across any module — skipping AI pass.")
        return 0

    all_candidates.sort(key=lambda t: (-t[0], -t[1]))

    for crit, total, filepath_str, issues, report, module_path in all_candidates:
        fp = Path(filepath_str)
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            print(f"  [AI] Cannot read {fp.name}: {exc} — skipped")
            continue
        file_bytes = len(content.encode("utf-8"))
        if total_bytes + file_bytes > CLAUDE_MAX_BUNDLE_BYTES:
            skipped_large.append(f"{module_path.name}/{fp.name}")
            report.issues.append(Issue(
                file=filepath_str, line=0, severity=SEVERITY_WARNING,
                category="AI Skip",
                message=f"{fp.name} exceeds the {CLAUDE_MAX_BUNDLE_BYTES // 1000}KB "
                        f"bundle limit and was not sent to AI",
                suggestion="Fix manually, or raise CLAUDE_MAX_BUNDLE_BYTES in the script",
                auto_fixable=False, fix_applied=False,
            ))
            continue
        file_key = f"{module_path.name}/{fp.name}"
        if file_key in file_map:
            file_key = f"{module_path.name}/{fp.relative_to(module_path)}"
        total_bytes += file_bytes
        file_map[file_key] = (filepath_str, content, issues, report, module_path)

    if not file_map:
        print("  [AI] All files exceeded the bundle size limit — nothing sent to AI.")
        return 0

    if skipped_large:
        print(f"  [AI] ⚠ Bundle-limit skipped: {', '.join(skipped_large)}")

    n_files  = len(file_map)
    n_issues = sum(len(v[2]) for v in file_map.values())
    n_mods   = len({v[4].name for v in file_map.values()})
    print(
        f"\n  [AI] Sending 1 request to Claude ({CLAUDE_MODEL}) "
        f"— {n_files} file(s) across {n_mods} module(s), "
        f"{n_issues} issue(s), ~{total_bytes // 1024}KB…"
    )

    slim_map = {k: (v[0], v[1], v[2]) for k, v in file_map.items()}
    prompt = _build_bundle_prompt(slim_map, from_version, to_version=to_version)

    try:
        raw_response = _call_claude_api(api_key, prompt, to_version=to_version)
    except RuntimeError as exc:
        print(f"  [AI] ✗ API call failed: {exc}")
        reports[0].issues.append(Issue(
            file=str(module_paths[0]), line=0, severity=SEVERITY_WARNING,
            category="AI Error",
            message=f"Claude API call failed: {exc}",
            suggestion="Check your API key and network, then retry with --ai-fix",
            auto_fixable=False, fix_applied=False,
        ))
        return 0

    if verbose:
        preview = raw_response[:400].replace("\n", "↵")
        print(f"  [AI] Response preview: {preview}…")

    try:
        bundle = _parse_bundle_response(raw_response)
    except ValueError as exc:
        print(f"  [AI] ✗ Could not parse AI response as JSON: {exc}")
        debug_path = run.log_dir / "ai_response_debug.txt"
        try:
            debug_path.write_text(raw_response, encoding="utf-8")
            print(f"  [AI]   Raw response saved → {debug_path}")
        except Exception:
            pass
        reports[0].issues.append(Issue(
            file=str(module_paths[0]), line=0, severity=SEVERITY_WARNING,
            category="AI Parse Error",
            message=f"AI returned unparseable response: {exc}",
            suggestion=f"Inspect ai_response_debug.txt and apply fixes manually",
            auto_fixable=False, fix_applied=False,
        ))
        return 0

    ai_files: dict   = bundle.get("files", {})
    ai_skipped: list = bundle.get("skipped", [])
    ai_notes: str    = bundle.get("notes", "")

    if ai_skipped:
        print(f"  [AI] Claude skipped (too complex): {', '.join(ai_skipped)}")
    if ai_notes and verbose:
        print(f"  [AI] Notes: {ai_notes}")

    # Plan each module's AI edits and validate each file on its own (approved partial-migration policy): an invalid
    # output refuses that file only; its valid siblings are still written and a refused file keeps its bytes.
    plans: dict = {}  # module name -> (module_path, report, [FileEdit])
    for file_key, (filepath_str, original, issues, report, module_path) in file_map.items():
        fp = Path(filepath_str)
        fixed_content = ai_files.get(file_key)
        if fixed_content is None:
            fixed_content = ai_files.get(fp.name)
        if fixed_content is None:
            rel = fp.relative_to(module_path)
            print(f"  [AI] ✗ {module_path.name}/{rel} — not in AI response, skipped")
            continue
        fixed_content = _ensure_newline(fixed_content)
        if fixed_content == original:
            rel = fp.relative_to(module_path)
            print(f"  [AI] ↔ {module_path.name}/{rel} — no changes")
            continue
        edit = FileEdit(path=fp, dest=fp, original=original, fixed=fixed_content, issues=issues)
        edit.rejection = validate_text(filepath_str, fixed_content) or ""
        edit.resolved = resolved_by_rescan(
            issues, scan_content(fixed_content, filepath_str, report.from_version, report.to_version))
        plans.setdefault(module_path.name, (module_path, report, []))[2].append(edit)

    fixed_count = 0
    for module_name, (module_path, report, edits) in plans.items():
        accepted = []
        for edit in edits:
            if not edit.rejection:
                accepted.append(edit)
                continue
            rel = edit.path.relative_to(module_path)
            print(f"  [AI] ⚠ {module_name}/{rel} — rejected: {edit.rejection}")
            report.issues.append(Issue(
                file=str(edit.path), line=0, severity=SEVERITY_WARNING,
                category="Fix Rejected",
                message=f"AI output for {rel.as_posix()} rejected: {edit.rejection}. "
                        f"This file was left unchanged; the other files of {module_name} are not affected.",
                suggestion="Fix this file by hand; its findings stay open",
                auto_fixable=False, rejection_reason=edit.rejection,
            ))
            run.log.append("edit_rejected", module=module_name, path=str(edit.path),
                       rules=sorted({i.category for i in edit.issues}),
                       reason=edit.rejection, source="ai")
        if not accepted:
            continue
        written = write_module(module_path, accepted, report)
        if report.blocked:
            print(f"  [AI] ✗ {module_name} — write failed, module restored; see report")
            continue
        for edit in accepted:
            print(f"  [AI] ✓ {module_name}/{edit.path.relative_to(module_path)}")
        fixed_count += written

    print(
        f"\n  [AI] Done — {fixed_count}/{n_files} file(s) updated "
        f"across {n_mods} module(s) in 1 API call."
    )
    return fixed_count


# ─────────────────────────────────────────────


class LegacyAnthropicProvider:
    """Registry entry for the wrapped legacy Claude call (ai_providers registry, P6 replaces it)."""

    key = "legacy-anthropic"
    contract_version = CONTRACT_VERSION

    def complete(self, prompt: str, *, api_key: str, to_version: int) -> str:
        return _call_claude_api(api_key, prompt, to_version=to_version)

    def fix_bundle(self, **kwargs) -> int:
        return fix_bundle(**kwargs)
