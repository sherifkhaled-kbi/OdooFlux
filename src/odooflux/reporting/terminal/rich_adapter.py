"""Optional rich adapter (D-07, T011). rich is imported lazily and only for ``--ui rich``; when it is not importable
the default ANSI renderer is used without error. The adapter renders the same model and the same counts: it only
swaps the module table for a rich table and keeps the other sections as the ANSI renderer's text."""

import io

from odooflux.reporting.options import RendererOptions, sanitize_text
from odooflux.reporting.terminal.ansi import STATUS_STYLE, render_terminal

UI_CHOICES = ("auto", "ansi", "rich")


def rich_available() -> bool:
    try:
        import rich  # noqa: F401  (lazy, optional)
    except ImportError:
        return False
    return True


def render_ui(report: dict, options: RendererOptions = None, *, ui: str = "auto", is_tty: bool = False):
    """Return (text, ui_used). ``auto`` and ``ansi`` use the stdlib renderer; ``rich`` falls back when absent."""
    options = options or RendererOptions()
    if ui not in UI_CHOICES:
        raise ValueError(f"ui must be one of {UI_CHOICES}, got {ui!r}")
    if ui == "rich" and rich_available():
        return render_rich(report, options, is_tty=is_tty), "rich"
    return render_terminal(report, options, is_tty=is_tty), "ansi"


def render_rich(report: dict, options: RendererOptions, *, is_tty: bool = False) -> str:
    from rich.console import Console  # lazy: optional dependency
    from rich.table import Table

    color = options.use_color(is_tty)
    base = render_terminal(report, RendererOptions(
        color="never", width=options.columns, max_findings_per_file=options.max_findings_per_file,
        show_fixed=options.show_fixed, min_severity=options.min_severity, verbose=options.verbose))
    head, _, rest = base.partition("\nMODULE RESULTS\n")
    _, _, tail = rest.partition("\nFINDINGS")
    buffer = io.StringIO()
    console = Console(file=buffer, width=options.columns, force_terminal=color, no_color=not color,
                      color_system="standard" if color else None, highlight=False, markup=False, emoji=False)
    console.print(head.rstrip("\n"))
    table = Table(title="MODULE RESULTS", title_justify="left")
    for column in ("Status", "Module", "Open C/W/I", "Fixed", "Rejected", "Layers"):
        table.add_column(column, overflow="fold")
    for m in report["modules"]:
        counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}
        for f in m["findings"]:
            if f["status"] in ("OPEN", "NEEDS_REVIEW"):
                counts[f["severity"]] += 1
        table.add_row(m["status"], sanitize_text(m["name"]),
                      f"{counts['CRITICAL']}/{counts['WARNING']}/{counts['INFO']}",
                      str(sum(1 for f in m["findings"] if f["status"] == "FIXED")),
                      str(sum(1 for f in m["findings"] if f["status"] == "REJECTED")),
                      " ".join(f"{k} {v['outcome']}" for k, v in sorted(m["layers"].items())),
                      style=STATUS_STYLE.get(m["status"]) if color else None)
    console.print(table)
    console.print("\nFINDINGS" + tail.rstrip("\n"))
    return buffer.getvalue()
