"""TST-011-081 (REQ-KAP-040, REQ-KAP-005; contracts/migration-integration.md "Report").

Optional `knowledge_release` on report model v1. Without a release the model, every renderer output and the schema
behaviour are byte-identical to before (schema_version 1.0.0, no new key). With a release the builder emits
schema_version 1.1.0 and the strict `knowledge_release` object, and the renderers print one release line.
"""

import hashlib
import json
import re
import unittest
from pathlib import Path

from ._setup import SRC  # noqa: F401
from . import fixtures
from .helpers import GOLDEN_DIR, golden_names
from .schema_validator import Validator, load

DIGEST = "a" * 64
RELEASE = {"release_id": "kr-aaaaaaaaaaaa", "digest": DIGEST, "builtin": False, "completeness": "PARTIAL",
           "steps_covered": [{"step": "17-18", "completeness": "COMPLETE"},
                             {"step": "18-19", "completeness": "PARTIAL"}]}
BUILTIN = {"release_id": "builtin", "digest": None, "builtin": True, "completeness": None, "steps_covered": []}

# sha256 of each renderer output for every golden scenario, recorded before the knowledge_release change (T081).
# Re-pinned in waves (AF-2, AF-9, PA-5/PA-6) and audited in VR-5 (specs/012 verification.md, "Report hash audit").
# Causes, by renderer: a dry run has recovery.reversible false, a null rollback_cmd, modules[].reversible false and
# "planned" edits (json, html, terminal). An unresolved finding adds location, reason_not_fixed and developer_action
# (json), prints L<line>:UNKNOWN and "Not fixed:" (terminal, html) and adds properties.reason_not_fixed (sarif). A
# refused edit makes the module PARTIAL and changes the rejected-edit wording (json, html, terminal); json also adds
# refused_files. The default terminal hides
# FIXED findings, so a scenario whose only finding is FIXED keeps its terminal pins; its sarif pins are unchanged
# because it has no unresolved finding. VR-5 gave the html badge and tile one status class token and a PARTIAL colour
# rule, which re-pinned every html entry.
PRE_CHANGE_HASHES = {
    "ai_enabled:html": "13d22f972ee59962d4aa04e1908c06c815c3fc2be7c7f300ad5b1d9598192b2a",
    "ai_enabled:json_renderer": "9524492196e86ef72a347facb744fcf974184d6ffdb0eac9fdc7cd86e100bd0d",
    "ai_enabled:json_v1": "9524492196e86ef72a347facb744fcf974184d6ffdb0eac9fdc7cd86e100bd0d",
    "ai_enabled:sarif": "22564c158e04d8af684607bbee704bcc7fd8ff5d98345ac99d1148e660dea08b",
    "ai_enabled:sarif_exit": "5ecb512d7c67fd6ade9d7caa44e92670a730136348b0dfc62a11dff3ddaa8696",
    "ai_enabled:terminal": "15502e0dc58b11fd9362860882566af9f26895598836fdee5bbdbf95a310c987",
    "ai_enabled:terminal_verbose": "5fe71108c95f3c5d850301443bf91f0150fe46c59c6ff6308674317535c70abc",
    "blocked:html": "d3953ffd4d1175538aa7fa94f5cf2914800ee48b8bd6f119617c8f0ae3a026d9",
    "blocked:json_renderer": "095a8d793e88e266ee3da26247847b743fbbfac8a3f281ac143f7a90a55dee4e",
    "blocked:json_v1": "095a8d793e88e266ee3da26247847b743fbbfac8a3f281ac143f7a90a55dee4e",
    "blocked:sarif": "ca74fb0dfb99b0f029ca488ba3ccfb96a5bec8d3450b8294a1f3d789e8d745bf",
    "blocked:sarif_exit": "490cd9348e462b6a33e6c7610d3b283a9af03e5f01ed45784d058431761a5736",
    "blocked:terminal": "1c0ae07499ba83ff435d07d4101e42c5f1f1c0520a60a35b33a695d14f16bb13",
    "blocked:terminal_verbose": "7c2b5cc4ebbf00787252a9c29f2ce113ca8bbfd37dfff0455791379b18d297fb",
    "failed:html": "7389ee871c2782bd79b77aa23da85b06dd07b85893892459ffc85a95600ab057",
    "failed:json_renderer": "ce5f915719e3aa5bdb8d7a6a0b43d02c0f356e958e86527bde2e046053bc8d70",
    "failed:json_v1": "ce5f915719e3aa5bdb8d7a6a0b43d02c0f356e958e86527bde2e046053bc8d70",
    "failed:sarif": "5004aaedb8ae195652d2173f95e02ee0ff7479edd42abffd33d4063060e67c21",
    "failed:sarif_exit": "2aa5e8be4367f150dc9a022695bf950b8b1a66ca3e230f2aed45bb40691bd271",
    "failed:terminal": "ced594888585bd33e6cce1936bd4208324cd2dcfdacb382cf4b198ad6a0c693a",
    "failed:terminal_verbose": "738e00386cef4ee8500381a1030dedfbde63c015b20f80765cb7988839e8c25f",
    "hostile:html": "288534f21640a008c8231531283d2de7c222f4645ee3aada98bc429b80c5b7a0",
    "hostile:json_renderer": "0c43d10d327a51d8d439e813285c1210afa5c860f47dc6d69aa7acd84dd0b663",
    "hostile:json_v1": "0c43d10d327a51d8d439e813285c1210afa5c860f47dc6d69aa7acd84dd0b663",
    "hostile:sarif": "6d845e3d6c06a644386824c7f6a6b61ff3c33fd871a25f75c9fc5ec2e04061f4",
    "hostile:sarif_exit": "c5ba9df97e26a3544da0cbd6a38a7d4fe2e0cc9f7242407822cdd3f77087b96d",
    "hostile:terminal": "d9d65bb911c39c21b3e48b138dffded1ce8f67867e70166ab718ca97a3a5fb7b",
    "hostile:terminal_verbose": "eb338eb2cc3df401532aaaf7fc535df40bbf8f1a5aa8659ea917708a72f510bd",
    "install_verified:html": "c8eb58b1c0571d5c4baa92d91ceedab6deb7680f4907b6e51917a16d55bafae1",
    "install_verified:json_renderer": "cd377dec7ddb652b860de996adfd05f26331d03226cac5df63a2ecd9a0196d1f",
    "install_verified:json_v1": "cd377dec7ddb652b860de996adfd05f26331d03226cac5df63a2ecd9a0196d1f",
    "install_verified:sarif": "e8e84f1e965917097de058b974d0936ff36ad06eb3561d5fa15271dd900076c9",
    "install_verified:sarif_exit": "b57ad2eeb19a90ea79cb5d3be9caf896e32dde150c9f6d85e2033b4ff6335300",
    "install_verified:terminal": "e32077abbead3b2489c17ec5de7554b59a17bc8bd341dc9a107f6eb1dc139599",
    "install_verified:terminal_verbose": "9fe30c849d03fca8ca14423c843d3d78ad08c5fc0d5751fd860c5ab7cdfc3cc3",
    "mixed:html": "d474e52e3ed8af825577c667f7904f16385adbe68682e2f5182c9ee823ecd159",
    "mixed:json_renderer": "12ec59ebab97942ac6885cc519308804c591bcf18dcb1d2fbc7db835e0710e11",
    "mixed:json_v1": "12ec59ebab97942ac6885cc519308804c591bcf18dcb1d2fbc7db835e0710e11",
    "mixed:sarif": "fca00a7bef806b2717d855ce18b0ba1ce47fd105296e13e68b6e42d92bd17fa3",
    "mixed:sarif_exit": "e4d2b0b62051971fdea63d1a306031193339e0a8998ab118319f6f563553a759",
    "mixed:terminal": "00f5a4aaae5093f8113ae0ea959fb20de0643c2f32c3a44a5d60991f8a6755d4",
    "mixed:terminal_verbose": "4a99da91f6a99c2bd0c35c78a3ec8b2c28e552622c31ccaa72b7e0f7642f722d",
    "needs_review:html": "92dcde2e9427566f58850893963fd8a95851353bbb2821d0830223496774a88e",
    "needs_review:json_renderer": "0042e21a33cf64bfe743839f42b494a06597d615960fdf0917bebb71150ce6c5",
    "needs_review:json_v1": "0042e21a33cf64bfe743839f42b494a06597d615960fdf0917bebb71150ce6c5",
    "needs_review:sarif": "c4376606959f0adc1fa67897a4b599700c01ad45675a0b9afa5575c36dead294",
    "needs_review:sarif_exit": "a178df9a45f88e1faf18b5ff852370f27691c0334ce21432d99bcbe2025b19d2",
    "needs_review:terminal": "818e67e7ec443f8fd49f77f8db446fc97213b1ffffa0da518e7e0173fca057e5",
    "needs_review:terminal_verbose": "a68fd64813c215590cccf718798cc321e982bf867817be2442f5ba53fcd682b1",
    "provisional:html": "a7fabbcd0f3dea43237e56e903b54c8cb429ca19f89e7bf9fad11fd5f61abfc4",
    "provisional:json_renderer": "be736557f8818f6b1c27cf5db84ce7c575050d8b41cd5ba3149e08a752113a1a",
    "provisional:json_v1": "be736557f8818f6b1c27cf5db84ce7c575050d8b41cd5ba3149e08a752113a1a",
    "provisional:sarif": "282cefe21dc6291303c8371a3df92580be010b8a070b25c67252f195dd7e4426",
    "provisional:sarif_exit": "bb66e1bd2a2f5927033cf5dc70a68edcd0feb7d19aafe1eed3ae4ed117bafcec",
    "provisional:terminal": "91eaa3611226f3cf3229b4f3656a4a93910974bccfc921a3664c95ae3d09376c",
    "provisional:terminal_verbose": "be6098ad0112686fbd39d1d52718d825ac2c00d11a0c0ed394fb38afb9dfbde9",
    "static_validated:html": "a8799c706008bdab0ad17c05f77ee96f316321e6247644f149030f9f7395cca3",
    "static_validated:json_renderer": "9c6cea175c4aad84254a27ef50872f01adef5297fa333846bb4c6485156c3c0d",
    "static_validated:json_v1": "9c6cea175c4aad84254a27ef50872f01adef5297fa333846bb4c6485156c3c0d",
    "static_validated:sarif": "2fcda912d33a8a34b761285b4664db36098db932585fce9a9eb131431626a5d4",
    "static_validated:sarif_exit": "2ad7e306892ec04dd0fb02ec72560d609cc50ad153d359f435d4cd87acbf889b",
    "static_validated:terminal": "6b850562821f8391f629999b20a08029ac02dbd12db837d621c37f457c3c2279",
    "static_validated:terminal_verbose": "d1efac975ad4c726d8a3e6e24e8e216043c8bde0e0914e4cb0152775121281b7",
    "verified_success:html": "c1f9ffd5fa1474b6896ef38e8115b94134830ad22b8e8b9c4bdf8e99c903cbf0",
    "verified_success:json_renderer": "f51929399845fff6bd6e34bb421b111f58332b69377ee76928a4ca57dc7ba121",
    "verified_success:json_v1": "f51929399845fff6bd6e34bb421b111f58332b69377ee76928a4ca57dc7ba121",
    "verified_success:sarif": "864def6b4bbe218113766d41c057b30cd8603815fbd59493e0f7510ab112cd2d",
    "verified_success:sarif_exit": "a49f17f1ed97d1c81eb2143f78dc29b930194259532d3172e908f77ec58666aa",
    "verified_success:terminal": "b173fe1485e40ad0481a5b66bbb2ecb827fa0f6cb934ae643c9cb0bdad2b05c0",
    "verified_success:terminal_verbose": "e1922db44d7bcae39280e7551de67dcead12fe664415b3958516acc9e0f32073",
}


def _schema():
    from odooflux.reporting.model.schema_check import SCHEMA_FILE
    return load(SCHEMA_FILE)


def _model(name="mixed", release=None):
    from odooflux.core.orchestrator.run import reports_from_state
    from odooflux.reporting.model.model import build_report
    state, kwargs = fixtures.scenarios()[name]
    return build_report(state, reports_from_state(state), run_log_path="/state/runs/run-golden/log/run.jsonl",
                        knowledge_release=release, **kwargs)


def _renders(model):
    from odooflux.reporting.exporters.json_v1 import export_json_v1
    from odooflux.reporting.exporters.sarif import export_sarif
    from odooflux.reporting.html.html import render_html
    from odooflux.reporting.model.json_renderer import JsonRenderer
    from odooflux.reporting.options import RendererOptions
    from odooflux.reporting.terminal.ansi import render_terminal
    return {
        "json_v1": export_json_v1(model),
        "json_renderer": JsonRenderer().render(model),
        "sarif": export_sarif(model),
        "sarif_exit": export_sarif(model, exit_code=1),
        "html": render_html(model),
        "terminal": render_terminal(model, RendererOptions(), is_tty=False),
        "terminal_verbose": render_terminal(model, RendererOptions(verbose=True), is_tty=False),
    }


def _strict_errors(document):
    """Schema check with the strict keywords (additionalProperties, pattern) that the stdlib subset in
    reporting/model/schema_check.py does not implement."""
    return Validator(_schema()).errors(document)


class ReportReleaseTests(unittest.TestCase):
    def test_no_release_bytes_identical(self):
        from odooflux.reporting.exporters.json_v1 import export_json_v1
        for name in golden_names():
            model = _model(name)
            self.assertEqual(model["schema_version"], "1.0.0", name)
            self.assertNotIn("knowledge_release", model, name)
            self.assertEqual(export_json_v1(model), (GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"), name)
            self.assertEqual(export_json_v1(_model(name, release=None)), export_json_v1(model), name)

    def test_no_release_renderer_hashes_unchanged(self):
        for name in sorted(PRE_CHANGE_HASHES):
            scenario, renderer = name.split(":")
            digest = hashlib.sha256(_renders(_model(scenario))[renderer].encode("utf-8")).hexdigest()
            self.assertEqual(digest, PRE_CHANGE_HASHES[name], name)

    def test_schema_accepts_both_versions(self):
        from odooflux.reporting.model.schema_check import validate_report
        old = _model("mixed")
        new = _model("mixed", release=RELEASE)
        self.assertEqual(new["schema_version"], "1.1.0")
        self.assertEqual(_strict_errors(old), [])
        self.assertEqual(_strict_errors(new), [])
        self.assertEqual(validate_report(old), [])
        self.assertEqual(validate_report(new), [])
        self.assertEqual(_model("mixed", release=BUILTIN)["knowledge_release"]["digest"], None)
        self.assertEqual(_strict_errors(_model("mixed", release=BUILTIN)), [])

    def test_schema_rejects_unknown_version(self):
        bad = json.loads(json.dumps(_model("mixed", release=RELEASE)))
        bad["schema_version"] = "1.2.0"
        self.assertTrue(_strict_errors(bad))

    def test_schema_rejects_malformed_knowledge_release(self):
        cases = {
            "missing release_id": lambda r: r.pop("release_id"),
            "missing digest": lambda r: r.pop("digest"),
            "extra key": lambda r: r.__setitem__("label", "x"),
            "short digest": lambda r: r.__setitem__("digest", "a" * 63),
            "uppercase digest": lambda r: r.__setitem__("digest", "A" * 64),
            "bad completeness": lambda r: r.__setitem__("completeness", "MAYBE"),
            "builtin not boolean": lambda r: r.__setitem__("builtin", "no"),
            "steps not list": lambda r: r.__setitem__("steps_covered", {}),
            "step without completeness": lambda r: r["steps_covered"].__setitem__(0, {"step": "17-18"}),
            "step bad completeness": lambda r: r["steps_covered"][0].__setitem__("completeness", "OK"),
            "step extra key": lambda r: r["steps_covered"][0].__setitem__("extra", 1),
        }
        for label, mutate in cases.items():
            bad = json.loads(json.dumps(_model("mixed", release=RELEASE)))
            mutate(bad["knowledge_release"])
            self.assertTrue(_strict_errors(bad), label)

    def test_release_object_has_the_contract_fields(self):
        model = _model("mixed", release=RELEASE)
        self.assertEqual(model["knowledge_release"], RELEASE)
        self.assertEqual(json.loads(_renders(model)["json_v1"])["knowledge_release"]["release_id"], "kr-aaaaaaaaaaaa")

    def test_release_line_in_renderers(self):
        model = _model("mixed", release=RELEASE)
        out = _renders(model)
        self.assertIn("kr-aaaaaaaaaaaa", out["html"])
        self.assertIn(DIGEST, out["html"])
        self.assertIn("kr-aaaaaaaaaaaa", out["terminal"])
        self.assertIn(DIGEST, out["terminal"])
        self.assertIn("kr-aaaaaaaaaaaa", out["sarif"])
        self.assertIn(DIGEST, out["sarif"])
        self.assertIn("kr-aaaaaaaaaaaa", out["json_v1"])
        self.assertIn("1.1.0", out["json_v1"])
        self.assertIn("kr-aaaaaaaaaaaa", out["terminal_verbose"])

    def test_release_absent_renderers_have_no_release_text(self):
        out = _renders(_model("mixed"))
        for key in ("html", "terminal", "sarif", "json_v1"):
            self.assertNotIn("knowledge", out[key].lower(), key)
            self.assertNotIn("kr-", out[key], key)

    def test_html_status_class_is_one_css_token(self):
        # VR-5: a PARTIAL module status ("PARTIAL — DEVELOPER ACTION REQUIRED") must not split into several class tokens
        # in the badge and tile, and must have its own colour rule like the other statuses.
        html = _renders(_model("mixed"))["html"]
        classes = re.findall(r'class="(?:badge|tile) ([^"]*)"', html)
        self.assertTrue(classes)
        for value in classes:
            self.assertRegex(value, r"^status-[A-Z_]+$")
        self.assertIn('class="badge status-PARTIAL"', html)
        self.assertRegex(html, r"\.status-PARTIAL[^{]*\{color:#8a4600\}")

    def test_model_builder_does_not_import_knowledge(self):
        from odooflux.reporting.model import model as module
        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("from odooflux.knowledge", source)
        self.assertNotIn("import odooflux.knowledge", source)
        self.assertNotIn("from odooflux.knowledge", source.replace("knowledge_release", ""))


if __name__ == "__main__":
    unittest.main()
