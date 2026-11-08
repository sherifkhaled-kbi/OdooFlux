"""TST-011-081 (REQ-KAP-040, REQ-KAP-005; contracts/migration-integration.md "Report").

Optional `knowledge_release` on report model v1. Without a release the model, every renderer output and the schema
behaviour are byte-identical to before (schema_version 1.0.0, no new key). With a release the builder emits
schema_version 1.1.0 and the strict `knowledge_release` object, and the renderers print one release line.
"""

import hashlib
import json
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
PRE_CHANGE_HASHES = {
    "ai_enabled:html": "a9d3d350b4307ac532202bcd1b7f06984be8688ee63b3c2653d021f6fc82c2a3",
    "ai_enabled:json_renderer": "43c40999e53f82d0452a30ec74b43ef65daa26a299588bd0856746400fce190a",
    "ai_enabled:json_v1": "43c40999e53f82d0452a30ec74b43ef65daa26a299588bd0856746400fce190a",
    "ai_enabled:sarif": "390695c0ea2c2fcdbe0f2cc4d582c044b544ddb48b52b5b103cd56226c2bbd24",
    "ai_enabled:sarif_exit": "529b54fbbbf4c8a4cc9416cba68dda122e558006d8857227c7e73b83a362f6b8",
    "ai_enabled:terminal": "2bf9fc35eeb730c361b85f4ef228d77783fd66c9de59d5aad503c38773b9d8fd",
    "ai_enabled:terminal_verbose": "a3dccffcc3df146a58bda2ccb59601a693c5e2a849790ffe9929e9a374383312",
    "blocked:html": "987e7cfa1c50cfdfa9af6002708cb11cc2c11b1d2ab7d56e1b90243bee8b7ae6",
    "blocked:json_renderer": "2b8b1aed3b07f7d9b79470ff1c365f88b7cbdb1c7d37ff6719e66eb7919966c0",
    "blocked:json_v1": "2b8b1aed3b07f7d9b79470ff1c365f88b7cbdb1c7d37ff6719e66eb7919966c0",
    "blocked:sarif": "ca74fb0dfb99b0f029ca488ba3ccfb96a5bec8d3450b8294a1f3d789e8d745bf",
    "blocked:sarif_exit": "490cd9348e462b6a33e6c7610d3b283a9af03e5f01ed45784d058431761a5736",
    "blocked:terminal": "1c0ae07499ba83ff435d07d4101e42c5f1f1c0520a60a35b33a695d14f16bb13",
    "blocked:terminal_verbose": "7c2b5cc4ebbf00787252a9c29f2ce113ca8bbfd37dfff0455791379b18d297fb",
    "failed:html": "0f6a2972090003d22ff6e9f62ff109c17a85ecfa1d99a22f34a62bb99a64147f",
    "failed:json_renderer": "9b43ff38aa63ad766f96c7802d40bbde5bc31f4e68550f0703b065c9ddf00f23",
    "failed:json_v1": "9b43ff38aa63ad766f96c7802d40bbde5bc31f4e68550f0703b065c9ddf00f23",
    "failed:sarif": "3716ff14658b960173dcb22416caed94545d957a722f1400fd79e2438da77a6b",
    "failed:sarif_exit": "70063b0ffb6eecb918bdde7b0439ac520f4af8ac63e00c40cb69822ab36d93a3",
    "failed:terminal": "df9ca45bf165bbbb6be412fbb95a9ea777368f87d555d5044f189e54029c2aa9",
    "failed:terminal_verbose": "82d4303647932db0b323ba961de220481717a8d5deb5fa0dcd12a385f71e588c",
    "hostile:html": "1fdbe087e73519c26a60435a38926c8b61613b4b924e42e1724b33e0d9f5c42f",
    "hostile:json_renderer": "f70e5f78fd18a08db412c9f16c5b169753fa3a6e52049c21d576fb855f569b9d",
    "hostile:json_v1": "f70e5f78fd18a08db412c9f16c5b169753fa3a6e52049c21d576fb855f569b9d",
    "hostile:sarif": "2d3badce65c9afb8693d6cea6ccb04c68e7b6db4142051cad7f522c0d28ca2ad",
    "hostile:sarif_exit": "864a0b1ea44b63a0e727c43b762ecab643c5d037601e209c1ba20bcb8dd82a32",
    "hostile:terminal": "bf4ef295ec4e1d53016ddc874d590e5eaf6af334f2e68a7fbcffbcae6285c287",
    "hostile:terminal_verbose": "1643091029aa174dc2788b59bbb5131b6afec529776c826e0b66a91096947ddd",
    "install_verified:html": "1728d432eb56db82d3833905c43592d9444cfdea0df5171d4ca01dd01085a4e8",
    "install_verified:json_renderer": "b202318888e6bc1bcf474b3b12fbfe95017981191fa02d48dc7164f60d87c4d4",
    "install_verified:json_v1": "b202318888e6bc1bcf474b3b12fbfe95017981191fa02d48dc7164f60d87c4d4",
    "install_verified:sarif": "e8e84f1e965917097de058b974d0936ff36ad06eb3561d5fa15271dd900076c9",
    "install_verified:sarif_exit": "b57ad2eeb19a90ea79cb5d3be9caf896e32dde150c9f6d85e2033b4ff6335300",
    "install_verified:terminal": "e32077abbead3b2489c17ec5de7554b59a17bc8bd341dc9a107f6eb1dc139599",
    "install_verified:terminal_verbose": "9fe30c849d03fca8ca14423c843d3d78ad08c5fc0d5751fd860c5ab7cdfc3cc3",
    "mixed:html": "b825a567fa6b7b157648e7e8b863f688fa0822294a4c89397ecad379d7d7e069",
    "mixed:json_renderer": "9c643c9b3c4fc5acfcc008c183428fd4593aa1a501c50c05520feb861e1a7df2",
    "mixed:json_v1": "9c643c9b3c4fc5acfcc008c183428fd4593aa1a501c50c05520feb861e1a7df2",
    "mixed:sarif": "05342abf2e2c7816dd97c97e55fc62a8d17a7d9fa29f5f54f18fb337e3e25d6a",
    "mixed:sarif_exit": "811c4421dad473d95973c77da74805a9165ba48390f3a85f8fa568f8a36df04f",
    "mixed:terminal": "6d552996afaa3f84e5c11710168f76ca4efc8509dec2c81a78c88625c615c3a7",
    "mixed:terminal_verbose": "3491590ade927c2ed36e4d6aac437282f93a94f288834d73038446e357af8662",
    "needs_review:html": "4da7dcf1a3b8a02f6f580ddf3040c331639931ff67db5a39921589405e871668",
    "needs_review:json_renderer": "1c3efce92f104ba8e7d846d0c3c7499c138544aae6a21647b150927b42c40f42",
    "needs_review:json_v1": "1c3efce92f104ba8e7d846d0c3c7499c138544aae6a21647b150927b42c40f42",
    "needs_review:sarif": "2090c3014375a4653264df54174d543ca06b54bdaa35fa9e3fc08227788e51c8",
    "needs_review:sarif_exit": "4e43e8d15954c442d5e3a82c889001d38b3ce546d2918ef8ef10d056d5cca0f0",
    "needs_review:terminal": "b122c039f30ca1d62ce35b5e44a768e3143544d0abe33ba9c7536f37661af0e5",
    "needs_review:terminal_verbose": "ea08baf741877831a2cbf825b22d88db9d05c88b8fc9b5222977fd7904d1f597",
    "provisional:html": "34413ffc63c488365a6682001bc34e3398d17bdb2dc113b58d20a1a1817bf6ee",
    "provisional:json_renderer": "233724be5866bde4b1eaf820bb0a570c3a2d6522aa62effdf7c73fb2d786a381",
    "provisional:json_v1": "233724be5866bde4b1eaf820bb0a570c3a2d6522aa62effdf7c73fb2d786a381",
    "provisional:sarif": "282cefe21dc6291303c8371a3df92580be010b8a070b25c67252f195dd7e4426",
    "provisional:sarif_exit": "bb66e1bd2a2f5927033cf5dc70a68edcd0feb7d19aafe1eed3ae4ed117bafcec",
    "provisional:terminal": "91eaa3611226f3cf3229b4f3656a4a93910974bccfc921a3664c95ae3d09376c",
    "provisional:terminal_verbose": "be6098ad0112686fbd39d1d52718d825ac2c00d11a0c0ed394fb38afb9dfbde9",
    "static_validated:html": "bf16916c17b343ec2243bd645508870d621790ddd8fb2c1d896a3b6dbcedbc33",
    "static_validated:json_renderer": "d086faedb9c73214bdfbc37cf90eb48a1b4108c8215ddbd6b280ce4d65473956",
    "static_validated:json_v1": "d086faedb9c73214bdfbc37cf90eb48a1b4108c8215ddbd6b280ce4d65473956",
    "static_validated:sarif": "d07b6f9a9b1003f9f9bbac0b23224b75a14d3b74c7c70b149f97630cfbc03dc2",
    "static_validated:sarif_exit": "b503f7141d7b88b9ee5f30b83d05014c4a8cc3d8034b9db21d308d9250a7303a",
    "static_validated:terminal": "d1fe17e4127cb050d7e5eee26c15e943f1fc77e9b2f3afd8e1cfce6f7ee8bdda",
    "static_validated:terminal_verbose": "43e90409490cce9f521fa2f06ed7715b4cd935c87aaca3b2a89d521a9c38e789",
    "verified_success:html": "e69a62102f065ec5d3b21c7ec5ea6a1f8614861da87cebd680a20132d40136c3",
    "verified_success:json_renderer": "01030265bc85281bd29797f9d65dcf1a647e2e376fefe1bab5d045c010a4e9f7",
    "verified_success:json_v1": "01030265bc85281bd29797f9d65dcf1a647e2e376fefe1bab5d045c010a4e9f7",
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

    def test_model_builder_does_not_import_knowledge(self):
        from odooflux.reporting.model import model as module
        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("from odooflux.knowledge", source)
        self.assertNotIn("import odooflux.knowledge", source)
        self.assertNotIn("from odooflux.knowledge", source.replace("knowledge_release", ""))


if __name__ == "__main__":
    unittest.main()
