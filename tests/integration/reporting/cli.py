"""In-process CLI runner that captures stdout and stderr together (usage errors go to stderr)."""

import contextlib
import io


def run_cli_main(args):
    from odooflux.builtins import main
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = main([str(a) for a in args])
    return code, buf.getvalue()
