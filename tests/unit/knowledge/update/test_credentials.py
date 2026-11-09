"""Feature 012 / Addendum A2: Enterprise credential resolution and the askpass stub (credentials.py).

Offline only. Tokens are dummy values. The resolver is driven through its `env` parameter, not the process environment.
Run: PYTHONPATH=src python3 -m unittest discover -s tests/unit/knowledge/update -p 'test_credentials.py' -t .
"""

import copy
import os
import pickle
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from odooflux.knowledge.update import credentials as cred
from odooflux.knowledge.update.credentials import CredentialError, Token

TOKEN = "tok-TEST-1234567890"  # dummy value


def _write(path: Path, data: bytes, mode: int = 0o600) -> Path:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    os.chmod(path, mode)
    return path


class _Fixture(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cred-test-")
        self.root = Path(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def token_file(self, data: bytes, mode: int = 0o600) -> str:
        return str(_write(self.root / "token", data, mode))


class TokenObjectTests(unittest.TestCase):
    def test_repr_and_str_never_reveal_the_value(self):
        token = Token(TOKEN)
        self.assertEqual(repr(token), "<token>")
        self.assertEqual(str(token), "<token>")
        self.assertEqual(f"{token}", "<token>")
        self.assertNotIn(TOKEN, repr([token]))
        self.assertNotIn(TOKEN, repr({"t": token}))

    def test_value_leaves_only_through_reveal_and_redact(self):
        token = Token(TOKEN)
        self.assertEqual(token.reveal(), TOKEN)
        self.assertEqual(token.redact(f"see {TOKEN} here"), "see *** here")
        self.assertFalse(hasattr(token, "__dict__"), "no attribute dictionary that could leak the value")

    def test_pickling_and_copying_are_refused(self):
        token = Token(TOKEN)
        with self.assertRaises(TypeError):
            pickle.dumps(token)
        with self.assertRaises(TypeError):
            copy.copy(token)
        with self.assertRaises(TypeError):
            copy.deepcopy(token)

    def test_invalid_values_are_refused_without_echo(self):
        for value in ("", "   ", "tok TEST", "tok\tTEST", "tok\x01TEST", "tok​TEST", "x" * 4097, 123):
            with self.subTest(value=repr(value)[:24]):
                with self.assertRaises(CredentialError) as ctx:
                    Token(value)
                self.assertEqual(ctx.exception.code, "TOKEN_INVALID")
                self.assertNotIn("TEST", str(ctx.exception))

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(Token(f"  {TOKEN}\n").reveal(), TOKEN)


class ResolveTokenTests(_Fixture):
    def test_neither_source_configured_gives_none(self):
        self.assertIsNone(cred.resolve_enterprise_token(env={}))
        self.assertIsNone(cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN": "   "}))
        self.assertIsNone(cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": ""}))

    def test_environment_token(self):
        token = cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN": TOKEN})
        self.assertIsInstance(token, Token)
        self.assertEqual(token.reveal(), TOKEN)

    def test_environment_wins_over_file_without_error(self):
        bad_file = self.token_file(b"tok TEST with spaces", 0o644)  # would fail validation if read
        token = cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN": TOKEN,
                                                   "ODOOFLUX_ENTERPRISE_TOKEN_FILE": bad_file})
        self.assertEqual(token.reveal(), TOKEN)

    def test_invalid_environment_token_is_refused_without_echo(self):
        with self.assertRaises(CredentialError) as ctx:
            cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN": "tok TEST"})
        self.assertEqual(ctx.exception.code, "TOKEN_INVALID")
        self.assertNotIn("TEST", str(ctx.exception))

    def test_valid_owner_only_file_with_trailing_newline(self):
        path = self.token_file((TOKEN + "\n").encode(), 0o600)
        self.assertEqual(cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": path}).reveal(), TOKEN)
        path_400 = self.token_file(TOKEN.encode(), 0o400)
        self.assertEqual(cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": path_400}).reveal(), TOKEN)

    def test_symlink_is_refused(self):
        target = self.token_file(TOKEN.encode(), 0o600)
        link = self.root / "link"
        os.symlink(target, link)
        with self.assertRaises(CredentialError) as ctx:
            cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": str(link)})
        self.assertEqual(ctx.exception.code, "TOKEN_FILE_SYMLINK")

    def test_loose_permissions_are_refused(self):
        for mode in (0o644, 0o640, 0o604, 0o660):
            with self.subTest(mode=oct(mode)):
                path = self.token_file(TOKEN.encode(), mode)
                with self.assertRaises(CredentialError) as ctx:
                    cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": path})
                self.assertEqual(ctx.exception.code, "TOKEN_FILE_PERMISSIONS")

    def test_oversize_file_is_refused(self):
        path = self.token_file(b"a" * (cred.MAX_TOKEN_FILE_BYTES + 1), 0o600)
        with self.assertRaises(CredentialError) as ctx:
            cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": path})
        self.assertEqual(ctx.exception.code, "TOKEN_FILE_TOO_LARGE")

    def test_padding_with_trailing_whitespace_is_still_size_bounded(self):
        path = self.token_file(TOKEN.encode() + b" " * (cred.MAX_TOKEN_FILE_BYTES + 10), 0o600)
        with self.assertRaises(CredentialError) as ctx:
            cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": path})
        self.assertEqual(ctx.exception.code, "TOKEN_FILE_TOO_LARGE")

    def test_whitespace_or_control_inside_is_refused(self):
        for data in (b"tok TEST", b"tok\tTEST", b"tok\nTEST\n", b"tok\x00TEST", "tok​TEST".encode("utf-8")):
            with self.subTest(data=data):
                path = self.token_file(data, 0o600)
                with self.assertRaises(CredentialError) as ctx:
                    cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": path})
                self.assertEqual(ctx.exception.code, "TOKEN_FILE_INVALID")
                self.assertNotIn("TEST", str(ctx.exception))

    def test_empty_file_is_refused(self):
        for data in (b"", b"\n", b"   \n\t"):
            with self.subTest(data=data):
                path = self.token_file(data, 0o600)
                with self.assertRaises(CredentialError) as ctx:
                    cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": path})
                self.assertEqual(ctx.exception.code, "TOKEN_FILE_EMPTY")

    def test_non_utf8_file_is_refused(self):
        path = self.token_file(b"tok\xff\xfe-TEST", 0o600)
        with self.assertRaises(CredentialError) as ctx:
            cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": path})
        self.assertEqual(ctx.exception.code, "TOKEN_FILE_NOT_UTF8")

    def test_missing_directory_and_fifo_are_refused(self):
        with self.assertRaises(CredentialError) as ctx:
            cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": str(self.root / "absent")})
        self.assertEqual(ctx.exception.code, "TOKEN_FILE_MISSING")
        directory = self.root / "dir"
        directory.mkdir()
        with self.assertRaises(CredentialError) as ctx:
            cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": str(directory)})
        self.assertEqual(ctx.exception.code, "TOKEN_FILE_NOT_REGULAR")
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(CredentialError) as ctx:
            cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": str(fifo)})
        self.assertEqual(ctx.exception.code, "TOKEN_FILE_NOT_REGULAR")

    def test_file_errors_never_echo_contents(self):
        path = self.token_file(b"tok-TEST-SECRET-VALUE with space", 0o600)
        with self.assertRaises(CredentialError) as ctx:
            cred.resolve_enterprise_token(env={"ODOOFLUX_ENTERPRISE_TOKEN_FILE": path})
        self.assertNotIn("SECRET", str(ctx.exception))
        self.assertNotIn("SECRET", ctx.exception.message)

    def test_unknown_error_code_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            CredentialError("NOT_A_CODE", "x")


class AskpassStubTests(_Fixture):
    def _run(self, stub, prompt, env=None):
        base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        base.update(env or {})
        return subprocess.run([str(stub), prompt], env=base, capture_output=True, timeout=30)

    def test_stub_content_holds_no_token(self):
        stub = cred.write_askpass_stub(self._private_dir())
        self.assertNotIn(TOKEN, stub.read_text(encoding="utf-8"))
        self.assertNotIn("tok-", stub.read_text(encoding="utf-8"))

    def test_stub_is_private_and_executable(self):
        directory = self._private_dir()
        stub = cred.write_askpass_stub(directory)
        self.assertEqual(stat.S_IMODE(os.stat(stub).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(directory).st_mode), 0o700)

    def test_stub_answers_username_and_password_prompts_only(self):
        stub = cred.write_askpass_stub(self._private_dir())
        env = {cred.ENV_SECRET: TOKEN}
        user = self._run(stub, "Username for 'https://github.com': ", env)
        self.assertEqual(user.returncode, 0)
        self.assertEqual(user.stdout, b"x-access-token\n")
        password = self._run(stub, "Password for 'https://x-access-token@github.com': ", env)
        self.assertEqual(password.returncode, 0)
        self.assertEqual(password.stdout, (TOKEN + "\n").encode())
        other = self._run(stub, "Passphrase for key: ", env)
        self.assertNotEqual(other.returncode, 0)
        self.assertEqual(other.stdout, b"")

    def test_password_prompt_without_secret_fails_silently(self):
        stub = cred.write_askpass_stub(self._private_dir())
        result = self._run(stub, "Password for 'https://github.com': ", {})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assertNotIn(TOKEN.encode(), result.stdout + result.stderr)

    def test_stub_is_never_overwritten(self):
        directory = self._private_dir()
        cred.write_askpass_stub(directory)
        with self.assertRaises(CredentialError) as ctx:
            cred.write_askpass_stub(directory)
        self.assertEqual(ctx.exception.code, "ASKPASS_FAILED")

    def test_stub_refuses_a_non_directory(self):
        not_dir = _write(self.root / "file", b"x")
        with self.assertRaises(CredentialError) as ctx:
            cred.write_askpass_stub(not_dir)
        self.assertEqual(ctx.exception.code, "ASKPASS_FAILED")

    def test_session_yields_a_stub_and_removes_it(self):
        with cred.askpass_session() as stub:
            directory = stub.parent
            self.assertTrue(stub.exists())
            self.assertEqual(stat.S_IMODE(os.stat(directory).st_mode), 0o700)
            self.assertNotIn(TOKEN, stub.read_text(encoding="utf-8"))
        self.assertFalse(directory.exists())

    def test_session_removes_directory_even_when_the_body_fails(self):
        seen = {}
        with self.assertRaises(RuntimeError):
            with cred.askpass_session() as stub:
                seen["dir"] = stub.parent
                raise RuntimeError("boom")
        self.assertFalse(seen["dir"].exists())

    def test_remove_helper_deletes_stub_and_empty_directory_only(self):
        directory = self._private_dir()
        stub = cred.write_askpass_stub(directory)
        cred.remove_askpass_stub(stub)
        self.assertFalse(stub.exists())
        self.assertFalse(directory.exists())
        keeper = self._private_dir()
        other = _write(keeper / "other.txt", b"keep me")
        stub2 = cred.write_askpass_stub(keeper)
        cred.remove_askpass_stub(stub2)
        self.assertTrue(other.exists(), "a non-empty directory is never removed")

    def _private_dir(self) -> Path:
        directory = Path(tempfile.mkdtemp(prefix="odooflux-askpass-test-", dir=self._tmp))
        os.chmod(directory, 0o700)
        return directory


class CaBundleResolutionTests(_Fixture):
    def setUp(self):
        super().setUp()
        self.ca = _write(self.root / "ca.pem", b"-----BEGIN CERTIFICATE-----\n", 0o644)

    def test_unset_or_empty_is_none(self):
        self.assertIsNone(cred.resolve_ca_bundle(env={}))
        self.assertIsNone(cred.resolve_ca_bundle(env={"ODOOFLUX_CA_BUNDLE": ""}))

    def test_absolute_regular_file_is_returned(self):
        self.assertEqual(cred.resolve_ca_bundle(env={"ODOOFLUX_CA_BUNDLE": str(self.ca)}), str(self.ca))

    def test_invalid_values_are_refused(self):
        cases = [
            ("relative/ca.pem", "CA_BUNDLE_INVALID"),
            (str(self.root / "missing.pem"), "CA_BUNDLE_MISSING"),
            (str(self.root), "CA_BUNDLE_INVALID"),
            (" " + str(self.ca), "CA_BUNDLE_INVALID"),
            (str(self.ca) + "\n", "CA_BUNDLE_INVALID"),
            (str(self.ca) + "\x01", "CA_BUNDLE_INVALID"),
        ]
        for value, code in cases:
            with self.subTest(value=value):
                with self.assertRaises(CredentialError) as ctx:
                    cred.resolve_ca_bundle(env={"ODOOFLUX_CA_BUNDLE": value})
                self.assertEqual(ctx.exception.code, code)


if __name__ == "__main__":
    unittest.main()
