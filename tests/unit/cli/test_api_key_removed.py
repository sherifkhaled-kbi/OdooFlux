"""TST-010-009 (T017; REQ-AI-008, FR-008, D-10): once the D-10 window has ended `--api-key` is rejected with exit 2 and
the value is never echoed. Inside the window it still warns without echoing (TST-007-014).

The window is a version mechanism (`odooflux.cli.deprecations`): `--api-key` is removed from `API_KEY_REMOVED_IN`
onward. The project owner has not recorded the D-10 window as decided; the register item holds the decision."""

import contextlib
import io
import unittest
from unittest import mock

from tests.unit import _setup  # noqa: F401

import odooflux
from odooflux.builtins import main
from odooflux.cli import deprecations

SECRET = "SECRET-VALUE-must-never-print-9f8e7d"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def after_window():
    return mock.patch.object(odooflux, "__version__", deprecations.API_KEY_REMOVED_IN)


class WindowMechanismTests(unittest.TestCase):
    def test_removal_follows_the_version(self):
        self.assertFalse(deprecations.api_key_removed("0.2.0"))
        self.assertFalse(deprecations.api_key_removed("0.2.99"))
        self.assertTrue(deprecations.api_key_removed(deprecations.API_KEY_REMOVED_IN))
        self.assertTrue(deprecations.api_key_removed("1.0.0"))

    def test_the_current_release_is_still_inside_the_window(self):
        self.assertFalse(deprecations.api_key_removed(), "bumping the version past the window is an owner decision")


class ApiKeyRemovedTests(unittest.TestCase):
    ARGS = ["--module", "/nonexistent-module", "--from-version", "14", "--no-color"]

    def test_rejected_with_exit_2_and_no_echo_after_the_window(self):
        with after_window():
            code, out, err = run([*self.ARGS, "--api-key", SECRET])
        self.assertEqual(code, 2)
        self.assertNotIn(SECRET, out + err)
        self.assertIn("--api-key", err)
        self.assertIn("removed", err)
        self.assertIn("ANTHROPIC_API_KEY", err)

    def test_equals_form_and_abbreviation_are_rejected_without_echo(self):
        with after_window():
            for argv in ([*self.ARGS, f"--api-key={SECRET}"], [*self.ARGS, "--api-k", SECRET]):
                code, out, err = run(argv)
                self.assertEqual(code, 2, argv)
                self.assertNotIn(SECRET, out + err)

    def test_other_usage_errors_never_echo_the_key(self):
        with after_window():
            code, out, err = run([*self.ARGS, "--api-key", SECRET, "--jobs", "notanumber"])
        self.assertEqual(code, 2)
        self.assertNotIn(SECRET, out + err)
        with after_window():
            code, out, err = run([*self.ARGS, "--api-key", SECRET, "--bogus", SECRET])
        self.assertEqual(code, 2)
        self.assertNotIn(SECRET, out + err)

    def test_resume_subcommand_rejects_it_too(self):
        with after_window():
            code, out, err = run(["resume", "some-run", "--api-key", SECRET])
        self.assertEqual(code, 2)
        self.assertNotIn(SECRET, out + err)

    def test_rejection_happens_before_any_work(self):
        with after_window(), mock.patch("odooflux.cli.migrate.run_migrate") as migrate:
            run([*self.ARGS, "--api-key", SECRET])
        migrate.assert_not_called()

    def test_inside_the_window_it_warns_and_does_not_echo(self):
        code, out, err = run([*self.ARGS, "--api-key", SECRET])
        self.assertNotIn(SECRET, out + err)
        self.assertIn("deprecated", out + err)
        self.assertEqual(code, 4)  # the module path does not exist: the run itself fails, not the option

    def test_help_does_not_advertise_the_removed_option_after_the_window(self):
        with after_window():
            _, out, _ = run(["migrate", "--help"])
        self.assertNotIn("--api-key", out)


if __name__ == "__main__":
    unittest.main()
