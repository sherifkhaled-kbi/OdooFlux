"""TST-007-020 (FR-019): the sensitive-content filter and minimisation; canaries never reach the transport."""

import unittest

from . import _helpers as h
from odooflux.ai.authorization import minimise_violations, sensitive_kinds
from odooflux.ai.providers.types import AIRequest, RESPONSE_SCHEMA

CANARIES = {
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----",
    "aws_key": "AKIAABCDEFGHIJKLMNOP",
    "password_literal": "db_password = 'hunter2hunter2'",
    "api_key_literal": 'API_KEY = "abcd1234efgh5678"',
    "token_header": "Authorization: Bearer abcdefghijklmnop0123456789",
    "provider_key": "sk-test-canary-0123456789abcdef",
    "conn_string": "postgresql://odoo:s3cretpass@db.internal:5432/prod",
    "odoo_master": "admin_passwd = supersecretmaster",
    "pg_dump": "-- PostgreSQL database dump\nSET statement_timeout = 0;",
    "copy_stdin": "COPY public.res_partner (id, name, email) FROM stdin;\n1\tAcme\ta@b.c\n\\.",
    "insert_rows": "INSERT INTO res_partner (id, name) VALUES (1, 'Acme'), (2, 'Foo');",
}
SAFE = [
    "def f(self):\n    return self.env['res.partner'].search([])\n",
    "password = fields.Char(string='Password')\n",
    "token = os.environ.get('TOKEN')\n",
    '<field name="name">sample</field>',
    "api_key = self.env['ir.config_parameter'].get_param('x')\n",
]


def request(content, path="models/a.py", system="sys"):
    return AIRequest(request_id="r", model="m", system=system, messages=[{"role": "user", "content": content}],
                     response_schema=RESPONSE_SCHEMA, max_output_tokens=10, budget_ref="job", cache_key="",
                     region={"path": path, "span": [0, 1], "kind": "function"}, provider="alpha",
                     data_categories=("source_python",))


class SensitiveFilterTests(unittest.TestCase):
    def test_each_canary_is_detected(self):
        for name, text in CANARIES.items():
            self.assertTrue(sensitive_kinds(f"x = 1\n{text}\ny = 2\n"), name)

    def test_ordinary_code_is_not_flagged(self):
        for text in SAFE:
            self.assertEqual(sensitive_kinds(text), [], text)

    def test_kinds_name_the_category_not_the_value(self):
        for kind in sensitive_kinds(CANARIES["provider_key"] + CANARIES["pg_dump"]):
            self.assertNotIn("canary", kind)


class MinimisationTests(unittest.TestCase):
    def test_module_relative_path_only(self):
        self.assertEqual(minimise_violations(request("x", path="models/a.py")), [])
        self.assertIn("path_not_relative", minimise_violations(request("x", path="/home/u/addons/m/a.py")))
        self.assertIn("path_not_relative", minimise_violations(request("x", path="../a.py")))
        self.assertIn("path_not_relative", minimise_violations(request("x", path="C:\\x\\a.py")))

    def test_system_prompt_carries_no_customer_code(self):
        self.assertIn("system_has_code_block", minimise_violations(request("x", system="<code>\nx\n</code>")))

    def test_only_user_messages(self):
        req = request("x")
        req.messages.append({"role": "assistant", "content": "prefill"})
        self.assertIn("unexpected_role", minimise_violations(req))


class CanaryNeverReachesTransportTests(unittest.TestCase):
    def test_canary_in_region_never_reaches_the_transport(self):
        from odooflux.ai.gateway import build_gateway
        from odooflux.ai.providers.catalog import load_catalog
        from tests.unit.ai._gateway_support import RecordingTransport, config_for, make_request, ok_openai
        transport = RecordingTransport([ok_openai("{}")] * len(CANARIES))
        gw = build_gateway(config_for("alpha", "m-one", grants={"alpha": ["source_python", "evidence_excerpt"]}),
                           load_catalog(extra=[h.test_catalog()]), environ={"ALPHA_KEY": "k-1234567890"},
                           transport_for=lambda name: transport)
        for name, text in CANARIES.items():
            resp = gw.complete(make_request("alpha", "m-one", text=text))
            self.assertEqual(resp.error_kind, "sensitive_content_excluded", name)
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
