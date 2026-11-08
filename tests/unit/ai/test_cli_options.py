"""TST-007-003/004 support (REQ-AI-001, FR-001, FR-014): CLI/config options, defaults, and configuration errors."""

import argparse
import unittest

from ._setup_path import SRC  # noqa: F401
from odooflux.cli.ai_options import AIConfig, add_ai_arguments, resolve_ai
from odooflux.cli.main import build_parser


def parse(*argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--ai-fix", action="store_true")
    add_ai_arguments(parser)
    return parser.parse_args(list(argv))


FULL = ["--ai", "--ai-consent-send-code", "--ai-provider", "alpha", "--ai-model", "m-one",
        "--ai-budget-job-tokens", "5000"]


class DefaultsTests(unittest.TestCase):
    def test_ai_is_off_by_default_and_provider_type_is_external(self):
        cfg, err = resolve_ai(parse(), {})
        self.assertIsNone(err)
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.provider_type, "external")  # ADR-017: external is the default provider type
        self.assertFalse(cfg.consent_send_code)
        self.assertFalse(cfg.kill_switch)
        self.assertEqual((cfg.provider, cfg.model, cfg.authorizations), ("", "", {}))
        self.assertEqual((cfg.max_retries, cfg.use_cache), (2, True))

    def test_enabling_does_not_pick_a_provider_or_model_for_you(self):
        for missing, args in (("--ai-provider", ["--ai", "--ai-consent-send-code"]),
                              ("--ai-model", ["--ai", "--ai-consent-send-code", "--ai-provider", "alpha"])):
            cfg, err = resolve_ai(parse(*args), {})
            self.assertIn(missing, err)

    def test_complete_configuration_is_accepted(self):
        cfg, err = resolve_ai(parse(*FULL, "--ai-authorize", "alpha=source_python,evidence_excerpt"), {})
        self.assertIsNone(err)
        self.assertTrue(cfg.enabled and cfg.consent_send_code)
        self.assertEqual(cfg.authorizations, {"alpha": ["evidence_excerpt", "source_python"]})
        self.assertEqual(cfg.budget_job_tokens, 5000)

    def test_consent_and_budget_are_mandatory(self):
        _, err = resolve_ai(parse("--ai", "--ai-provider", "alpha", "--ai-model", "m", "--ai-budget-job-tokens", "1"), {})
        self.assertIn("--ai-consent-send-code", err)
        _, err = resolve_ai(parse("--ai", "--ai-consent-send-code", "--ai-provider", "alpha", "--ai-model", "m"), {})
        self.assertIn("--ai-budget-job-tokens", err)

    def test_kill_switch_flag_and_environment(self):
        self.assertTrue(resolve_ai(parse(*FULL, "--ai-disable-external"), {})[0].kill_switch)
        self.assertTrue(resolve_ai(parse(*FULL), {"ODOOFLUX_AI_DISABLE_EXTERNAL": "1"})[0].kill_switch)
        self.assertFalse(resolve_ai(parse(*FULL), {"ODOOFLUX_AI_DISABLE_EXTERNAL": "0"})[0].kill_switch)

    def test_fake_script_from_environment(self):
        cfg, _ = resolve_ai(parse(*FULL), {"ODOOFLUX_AI_FAKE_SCRIPT": "/tmp/x.json"})
        self.assertEqual(cfg.fake_script, "/tmp/x.json")

    def test_bad_values_are_configuration_errors(self):
        for extra in (["--ai-authorize", "alpha"], ["--ai-budget-module-tokens", "0"], ["--ai-timeout", "0"],
                      ["--ai-max-retries", "-1"], ["--ai-fix"]):
            _, err = resolve_ai(parse(*FULL, *extra), {})
            self.assertTrue(err, extra)

    def test_config_dict_never_holds_a_credential(self):
        d = resolve_ai(parse(*FULL), {"ALPHA_KEY": "canary-secret-value"})[0].to_dict()
        self.assertNotIn("canary-secret-value", repr(d))
        self.assertFalse(any("key" in k and "env" not in k and k != "secrets_file" for k in d))

    def test_options_are_registered_on_migrate_only(self):
        parser = build_parser()
        ns = parser.parse_args(["migrate", "--module", "x", "--from-version", "14", "--ai",
                                "--ai-consent-send-code", "--ai-provider", "p", "--ai-model", "m"])
        self.assertTrue(ns.ai and ns.ai_consent_send_code)
        self.assertEqual(ns.ai_provider_type, "external")


if __name__ == "__main__":
    unittest.main()


class LegacyAiFixKillSwitchTests(unittest.TestCase):
    """Review R2 finding: the legacy whole-file --ai-fix path must honour the external-transmission kill switch."""

    def test_ai_fix_is_refused_when_the_kill_switch_env_is_set(self):
        _cfg, err = resolve_ai(parse("--ai-fix"), {"ODOOFLUX_AI_DISABLE_EXTERNAL": "1"})
        self.assertIsNotNone(err)
        self.assertIn("kill switch", err)

    def test_ai_fix_is_refused_when_the_kill_switch_flag_is_set(self):
        _cfg, err = resolve_ai(parse("--ai-fix", "--ai-disable-external"), {})
        self.assertIsNotNone(err)

    def test_ai_fix_without_kill_switch_is_not_affected(self):
        _cfg, err = resolve_ai(parse("--ai-fix"), {})
        self.assertIsNone(err)
