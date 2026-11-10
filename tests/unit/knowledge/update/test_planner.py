"""Feature 012 incremental update planner (plan Addendum B4, T05): decisions, carry-forward, pairs, fingerprint inputs,
blocking rules, determinism, JSON safety and spec shape against the shipped source registry. Stdlib unittest; pure
functions only, so no repository state is written.
"""

import hashlib
import json
import unittest

from odooflux.knowledge.acquisition import sources as registry
from odooflux.knowledge.update import catalog as cat
from odooflux.knowledge.update import fingerprint as fp
from odooflux.knowledge.update import planner as pl
from odooflux.knowledge.update.model import CheckReport, InstalledState, NewVersion, SourceCheck

CATALOG = cat.load_catalog()
ALLOW = registry.load_allow_list()
COMMUNITY = CATALOG.versions("community")
ENTERPRISE = CATALOG.versions("enterprise")
BUILD_CONFIG = {"profile": "default"}
RULE_SCHEMA = "1"
EXTRACTOR = "1"


def sha(tag: str, version: str) -> str:
    return hashlib.sha1(f"{tag}:{version}".encode("utf-8")).hexdigest()


def check(*, c_over=None, e_over=None, ent_status="SKIPPED_NO_CREDENTIALS", c_status="OK",
          statuses=("KNOWLEDGE_UPDATE_AVAILABLE",), new_versions=(), digest=None):
    """A CheckReport over the real catalog. Community defaults to remote = sha('c', v); Enterprise (when its status is
    OK) defaults to sha('e', v). Overrides map version -> sha."""
    c_over, e_over = c_over or {}, e_over or {}
    rows = []
    for entry in CATALOG.entries:
        sid = CATALOG.source_id(entry)
        if entry.edition == "community":
            remote = c_over.get(entry.version, sha("c", entry.version)) if c_status == "OK" else None
            rows.append(SourceCheck(sid, "community", entry.version, remote, None, c_status))
        else:
            remote = e_over.get(entry.version, sha("e", entry.version)) if ent_status == "OK" else None
            rows.append(SourceCheck(sid, "enterprise", entry.version, remote, None, ent_status))
    return CheckReport("odooflux.knowledge-check/1", tuple(statuses), tuple(rows), tuple(new_versions), (),
                       "FRESH" if ent_status == "OK" else "UNKNOWN", digest or CATALOG.digest, False, None)


def installed(*, community=COMMUNITY, enterprise=(), c_inst=None, release_id="rel-1", valid=True):
    """Installed state with a 40-hex pinned revision per source; defaults equal the check defaults (unchanged)."""
    c_inst = c_inst or {}
    revs = {}
    for v in community:
        revs[f"odoo-community-{v}"] = c_inst.get(v, sha("c", v))
    for v in enterprise:
        revs[f"odoo-enterprise-{v}"] = sha("e", v)
    return InstalledState(release_id=release_id, digest="d" * 64, revisions=revs, valid=valid,
                          problem=None if valid else "corrupt state")


def plan(chk, state, *, token=False, require=False, only_pair=None, last_inputs=None, extractor=EXTRACTOR,
         rule=RULE_SCHEMA, config=BUILD_CONFIG):
    return pl.plan_update(CATALOG, chk, state, token_available=token, require_enterprise=require,
                          only_pair=only_pair, extractor_version=extractor, rule_schema_version=rule,
                          build_config=config, last_inputs=last_inputs)


def previous_inputs(state, *, token=False):
    """Inputs of an earlier plan made from the same installed state with nothing changed (NOOP baseline)."""
    return plan(check(ent_status="OK" if token else "SKIPPED_NO_CREDENTIALS"), state, token=token).planning_inputs


def by_id(p):
    return {s.source_id: s for s in p.sources}


def labels(p):
    return [pr["step"] for pr in p.pairs]


class FreshInstallTests(unittest.TestCase):
    def test_fresh_install_community_only_builds_community_pairs_and_skips_enterprise(self):
        p = plan(check(), InstalledState(), token=False)
        self.assertEqual(p.decision, "BUILD")
        self.assertIsNone(p.blocking_reason)
        srcs = by_id(p)
        for v in COMMUNITY:
            self.assertEqual(srcs[f"odoo-community-{v}"].action, "ACQUIRE")
        for v in ENTERPRISE:
            self.assertEqual(srcs[f"odoo-enterprise-{v}"].action, "SKIP")
            self.assertIsNone(srcs[f"odoo-enterprise-{v}"].target_sha)
        self.assertEqual(p.carried_forward, [])
        self.assertEqual(len(p.pairs), len(COMMUNITY) - 1)
        self.assertTrue(all(pr["from"].startswith("odoo-community-") for pr in p.pairs))
        self.assertIsInstance(p.planning_fingerprint, str)
        self.assertIn(pl.PENDING_FINGERPRINT, p.reasons)
        self.assertIn("no previous fingerprint inputs recorded; full plan", p.reasons)

    def test_fingerprint_source_keys_are_registry_source_ids(self):
        p = plan(check(), InstalledState(), token=False)
        self.assertEqual(set(p.planning_inputs["source_shas"]),
                         {f"odoo-community-{v}" for v in COMMUNITY})

    def test_acquired_specs_carry_the_catalog_licence_and_no_placeholder(self):
        p = plan(check(ent_status="OK"), InstalledState(), token=True)
        for s in p.sources:
            if s.action != "ACQUIRE":
                continue
            entry = CATALOG.entry_for(s.version, s.edition)
            self.assertEqual(s.spec["licence_id"], entry.licence_id)
            self.assertEqual(s.spec["licence_access"], entry.licence_access)
            self.assertNotEqual(s.spec["licence_id"], "UNKNOWN")
        self.assertFalse(any("licence" in reason for reason in p.reasons))
        self.assertFalse(hasattr(pl, "LICENCE_UNVERIFIED"))

    def test_fresh_install_with_token_builds_both_families_with_duplicate_step_labels(self):
        p = plan(check(ent_status="OK"), InstalledState(), token=True)
        self.assertEqual(p.decision, "BUILD")
        srcs = by_id(p)
        self.assertTrue(all(srcs[f"odoo-enterprise-{v}"].action == "ACQUIRE" for v in ENTERPRISE))
        self.assertEqual(len(p.pairs), 2 * (len(COMMUNITY) - 1))
        self.assertEqual(labels(p).count("16-17"), 2)
        self.assertEqual(labels(p).count("12-13"), 2)
        enterprise_pairs = [pr for pr in p.pairs if pr["from"].startswith("odoo-enterprise-")]
        self.assertEqual(len(enterprise_pairs), len(ENTERPRISE) - 1)


class NoopTests(unittest.TestCase):
    def test_no_changes_is_noop_with_no_release(self):
        state = installed(enterprise=ENTERPRISE)
        p = plan(check(ent_status="OK"), state, token=True, last_inputs=previous_inputs(state, token=True))
        self.assertEqual(p.decision, "NOOP")
        self.assertIn(pl.NO_INPUT_CHANGE, p.reasons)
        self.assertEqual(p.pairs, [])
        self.assertEqual(p.change_explanation, [])
        self.assertTrue(all(s.action == "CARRY_FORWARD" for s in p.sources))
        self.assertIsInstance(p.planning_fingerprint, str)

    def test_noop_without_previous_inputs_is_build_not_silent(self):
        state = installed()
        p = plan(check(), state, last_inputs=None)
        self.assertEqual(p.decision, "BUILD")
        self.assertIn("no previous fingerprint inputs recorded; full plan", p.reasons)


class ChangeTests(unittest.TestCase):
    def test_single_community_revision_change_acquires_only_affected_pairs(self):
        state = installed()
        base = previous_inputs(state)
        p = plan(check(c_over={"17.0": sha("c2", "17.0")}), state, last_inputs=base)
        self.assertEqual(p.decision, "BUILD")
        srcs = by_id(p)
        self.assertEqual(srcs["odoo-community-17.0"].action, "ACQUIRE")
        self.assertEqual(srcs["odoo-community-17.0"].target_sha, sha("c2", "17.0"))
        self.assertEqual(srcs["odoo-community-16.0"].action, "CARRY_FORWARD")
        self.assertEqual(srcs["odoo-community-18.0"].action, "CARRY_FORWARD")
        self.assertEqual(labels(p), ["16-17", "17-18"])
        self.assertIn("odoo-community-16.0", p.carried_forward)
        self.assertNotIn("odoo-community-17.0", p.carried_forward)
        self.assertEqual(p.change_explanation, ["source_shas"])
        self.assertIn("odoo-community-17.0: revision changed; acquire", p.reasons)

    def test_multiple_changes_plan_each_affected_pair(self):
        state = installed()
        p = plan(check(c_over={"15.0": sha("c2", "15.0"), "18.0": sha("c2", "18.0")}), state,
                 last_inputs=previous_inputs(state))
        self.assertEqual(p.decision, "BUILD")
        self.assertEqual(labels(p), ["14-15", "15-16", "17-18", "18-19"])

    def test_new_major_version_only_is_noop_and_never_planned(self):
        state = installed()
        nv = NewVersion("community", "20.0", "20.0", sha("n", "20.0"))
        p = plan(check(new_versions=(nv,)), state, last_inputs=previous_inputs(state))
        self.assertEqual(p.decision, "NOOP")
        self.assertIn(pl.NOT_PLANNED, " ".join(p.reasons))
        self.assertTrue(all("20.0" not in s.source_id for s in p.sources))
        self.assertEqual(p.pairs, [])


class EnterpriseTests(unittest.TestCase):
    def test_enterprise_installed_without_token_is_carried_never_removed_or_skipped(self):
        state = installed(enterprise=ENTERPRISE)
        p = plan(check(), state, token=False, last_inputs=previous_inputs(state))
        srcs = by_id(p)
        for v in ENTERPRISE:
            sid = f"odoo-enterprise-{v}"
            self.assertEqual(srcs[sid].action, "CARRY_FORWARD")
            self.assertIn(sid, p.carried_forward)
            self.assertNotEqual(srcs[sid].action, "SKIP")
        self.assertEqual(p.decision, "NOOP")
        self.assertIsNone(p.blocking_reason)

    def test_enterprise_installed_with_token_and_change_acquires(self):
        state = installed(enterprise=ENTERPRISE)
        chk = check(ent_status="OK", e_over={"17.0": sha("e2", "17.0")})
        p = plan(chk, state, token=True, last_inputs=previous_inputs(state, token=True))
        srcs = by_id(p)
        self.assertEqual(srcs["odoo-enterprise-17.0"].action, "ACQUIRE")
        self.assertEqual(srcs["odoo-enterprise-17.0"].target_sha, sha("e2", "17.0"))
        self.assertEqual(srcs["odoo-enterprise-16.0"].action, "CARRY_FORWARD")
        self.assertEqual(p.decision, "BUILD")
        self.assertEqual(sorted(labels(p)), ["16-17", "17-18"])
        self.assertTrue(all(pr["from"].startswith("odoo-enterprise-") for pr in p.pairs))

    def test_auth_failed_without_require_carries_installed_and_names_code(self):
        state = installed(enterprise=ENTERPRISE)
        p = plan(check(ent_status="AUTH_FAILED"), state, token=True, last_inputs=previous_inputs(state))
        self.assertIsNone(p.blocking_reason)
        self.assertEqual(by_id(p)["odoo-enterprise-17.0"].action, "CARRY_FORWARD")
        self.assertTrue(any("ENTERPRISE_AUTH_FAILED" in r for r in p.reasons))

    def test_require_enterprise_without_token_is_blocked_with_nothing_acquired(self):
        p = plan(check(), installed(), token=False, require=True)
        self.assertEqual(p.decision, "BLOCKED")
        self.assertEqual(p.blocking_reason, "ENTERPRISE_REQUIRED_UNAVAILABLE")
        self.assertFalse(any(s.action == "ACQUIRE" for s in p.sources))
        self.assertEqual(p.pairs, [])
        self.assertIsNone(p.planning_fingerprint)

    def test_require_enterprise_with_auth_failed_is_blocked(self):
        p = plan(check(ent_status="AUTH_FAILED"), installed(), token=True, require=True)
        self.assertEqual(p.decision, "BLOCKED")
        self.assertEqual(p.blocking_reason, "ENTERPRISE_AUTH_FAILED")
        self.assertFalse(any(s.action == "ACQUIRE" for s in p.sources))
        self.assertEqual(p.pairs, [])

    def test_require_enterprise_unavailable_is_blocked(self):
        p = plan(check(ent_status="UNAVAILABLE"), installed(), token=True, require=True)
        self.assertEqual(p.blocking_reason, "ENTERPRISE_UNAVAILABLE")
        self.assertFalse(any(s.action == "ACQUIRE" for s in p.sources))

    def test_require_enterprise_blocked_plan_downgrades_community_acquisition_too(self):
        state = installed()
        p = plan(check(c_over={"17.0": sha("c2", "17.0")}), state, token=False, require=True,
                 last_inputs=previous_inputs(state))
        self.assertEqual(p.decision, "BLOCKED")
        self.assertEqual(by_id(p)["odoo-community-17.0"].action, "CARRY_FORWARD")
        self.assertIn("odoo-community-17.0", p.carried_forward)


class BlockingTests(unittest.TestCase):
    def test_offline_check_is_blocked_check_unavailable(self):
        chk = check(c_status="SKIPPED_OFFLINE", statuses=("CHECK_UNAVAILABLE",))
        p = plan(chk, installed(), token=False)
        self.assertEqual(p.decision, "BLOCKED")
        self.assertEqual(p.blocking_reason, "CHECK_UNAVAILABLE")
        self.assertEqual(p.pairs, [])

    def test_community_remote_not_read_is_blocked(self):
        p = plan(check(c_status="UNAVAILABLE", statuses=("NO_UPDATE",)), installed(), token=False)
        self.assertEqual(p.decision, "BLOCKED")
        self.assertEqual(p.blocking_reason, "CHECK_UNAVAILABLE")

    def test_invalid_installed_state_is_blocked(self):
        p = plan(check(), installed(valid=False), token=False)
        self.assertEqual(p.decision, "BLOCKED")
        self.assertEqual(p.blocking_reason, "LOCAL_STATE_INVALID")
        self.assertEqual(p.pairs, [])

    def test_local_state_invalid_status_is_blocked(self):
        p = plan(check(statuses=("LOCAL_STATE_INVALID",)), installed(), token=False)
        self.assertEqual(p.blocking_reason, "LOCAL_STATE_INVALID")

    def test_check_for_a_different_catalog_is_blocked(self):
        p = plan(check(digest="0" * 64), installed(), token=False)
        self.assertEqual(p.blocking_reason, "CHECK_CATALOG_MISMATCH")


class InputChangeTests(unittest.TestCase):
    def test_catalog_digest_change_forces_build_without_source_change(self):
        state = installed(enterprise=ENTERPRISE)
        last = dict(previous_inputs(state))
        last["catalog_digest"] = "0" * 64
        p = plan(check(), state, last_inputs=last)
        self.assertEqual(p.decision, "BUILD")
        self.assertEqual(p.change_explanation, ["catalog_digest"])
        self.assertIn("input changed: catalog_digest", p.reasons)
        self.assertFalse(any(s.action == "ACQUIRE" for s in p.sources))

    def test_extractor_change_forces_build_and_all_pairs(self):
        state = installed()
        last = previous_inputs(state)
        p = plan(check(), state, last_inputs=last, extractor="2")
        self.assertEqual(p.decision, "BUILD")
        self.assertEqual(p.change_explanation, ["extractor_version"])
        self.assertIn("input changed: extractor_version", p.reasons)
        self.assertEqual(len(p.pairs), len(COMMUNITY) - 1)

    def test_rule_schema_and_build_config_changes_are_named(self):
        state = installed()
        last = previous_inputs(state)
        p = plan(check(), state, last_inputs=last, rule="2", config={"profile": "other"})
        self.assertEqual(p.decision, "BUILD")
        self.assertEqual(p.change_explanation, ["build_config", "rule_schema_version"])


class ScopeTests(unittest.TestCase):
    def test_only_pair_restricts_pairs(self):
        state = installed()
        p = plan(check(c_over={"17.0": sha("c2", "17.0")}), state, only_pair=("17", "18"),
                 last_inputs=previous_inputs(state))
        self.assertEqual(p.decision, "BUILD")
        self.assertEqual(labels(p), ["17-18"])
        self.assertEqual(p.pairs[0]["from"], "odoo-community-17.0")

    def test_only_pair_outside_the_change_plans_no_pairs(self):
        state = installed()
        p = plan(check(c_over={"17.0": sha("c2", "17.0")}), state, only_pair=("18", "19"),
                 last_inputs=previous_inputs(state))
        # 17.0 changed upstream but is outside the scoped pair: it is carried, not refetched, so nothing builds
        self.assertEqual(p.decision, "NOOP")
        self.assertEqual(p.pairs, [])


class DeterminismAndOutputTests(unittest.TestCase):
    def test_plan_twice_is_equal(self):
        state = installed(enterprise=ENTERPRISE)
        chk = check(ent_status="OK", c_over={"16.0": sha("c2", "16.0")})
        last = previous_inputs(state, token=True)
        a = plan(chk, state, token=True, last_inputs=last)
        b = plan(chk, state, token=True, last_inputs=last)
        self.assertEqual(a, b)
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(json.dumps(a.to_dict(), sort_keys=True), json.dumps(b.to_dict(), sort_keys=True))

    def test_to_dict_is_json_and_carries_no_token_like_data(self):
        fake_token = "ghp_" + "A" * 36
        state = installed(enterprise=ENTERPRISE)
        for p in (plan(check(ent_status="OK"), InstalledState(), token=True),
                  plan(check(), state, token=False, require=True)):
            text = json.dumps(p.to_dict(), sort_keys=True)
            self.assertNotIn(fake_token, text)
            for word in ("token", "password", "secret", "bearer", "ghp_", "github_pat"):
                self.assertNotIn(word, text.lower(), word)

    def test_no_url_credentials_in_specs(self):
        p = plan(check(ent_status="OK"), InstalledState(), token=True)
        for s in p.sources:
            if s.spec:
                self.assertFalse(registry.has_url_credentials(s.spec["url"]))


class SpecShapeTests(unittest.TestCase):
    """Every ACQUIRE spec must be accepted by the real registry rules (validate_spec and SourceRegistry.add)."""

    def test_acquire_specs_validate_and_register(self):
        p = plan(check(ent_status="OK"), InstalledState(), token=True)
        acquires = [s for s in p.sources if s.action == "ACQUIRE"]
        self.assertEqual(len(acquires), len(COMMUNITY) + len(ENTERPRISE))
        for s in acquires:
            self.assertEqual(registry.validate_spec(s.spec, ALLOW), [], s.source_id)
            reg = registry.SourceRegistry(ALLOW)
            reg.add(s.spec)
            self.assertEqual(reg.get(s.source_id)["revision"], s.target_sha)

    def test_spec_fields_follow_the_registry_schema(self):
        p = plan(check(ent_status="OK"), InstalledState(), token=True)
        srcs = by_id(p)
        comm = srcs["odoo-community-17.0"].spec
        ent = srcs["odoo-enterprise-17.0"].spec
        self.assertEqual(comm["url"], "https://github.com/odoo/odoo/")
        self.assertTrue(comm["official"])
        self.assertEqual(comm["kind"], "GIT_COMMUNITY")
        self.assertEqual(comm["licence_id"], "LGPL-3.0-only")
        self.assertEqual(comm["licence_access"], "PUBLIC_OPEN")
        self.assertEqual(ent["url"], "https://github.com/odoo/enterprise/")
        self.assertTrue(ent["official"])
        self.assertEqual(ent["kind"], "GIT_ENTERPRISE")
        self.assertEqual(ent["licence_id"], "OEEL-1")
        self.assertEqual(ent["licence_access"], "ENTERPRISE_AUTHORIZED")
        self.assertNotIn("enterprise_derived", ent)
        self.assertNotIn("redistribution", ent)
        self.assertEqual(comm["revision"], srcs["odoo-community-17.0"].target_sha)
        self.assertEqual((comm["status"], comm["retrieved_at"], comm["checksum"], comm["failure_reason"]),
                         ("DECLARED", None, None, None))
        self.assertEqual(comm["branch"], "17.0")
        self.assertTrue(comm["required"])
        self.assertFalse(ent["required"])

    def test_skip_sources_have_no_spec_and_carried_catalog_sources_do(self):
        state = installed(enterprise=ENTERPRISE)
        p = plan(check(), state, token=False, last_inputs=previous_inputs(state))
        self.assertTrue(all(s.spec == {} for s in p.sources if s.action == "SKIP"))
        carried = [s for s in p.sources if s.action == "CARRY_FORWARD" and s.edition in ("community", "enterprise")]
        self.assertTrue(carried)
        self.assertTrue(all(s.spec["revision"] == s.installed_sha for s in carried))


class CarryOverTests(unittest.TestCase):
    def test_installed_source_absent_from_catalog_is_carried_not_removed(self):
        state = installed()
        revs = dict(state.revisions)
        revs["odoo-community-9.0"] = sha("c", "9.0")
        state = InstalledState(release_id="rel-1", digest="d" * 64, revisions=revs, valid=True)
        p = plan(check(), state, last_inputs=previous_inputs(state))
        self.assertIn("odoo-community-9.0", p.carried_forward)
        self.assertTrue(any("absent from the current catalog" in r for r in p.reasons))
        self.assertEqual(p.decision, "NOOP")


def _digest(tag: str) -> str:
    """A 64-hex stand-in for a verified snapshot digest (what acquisition + verification would have produced)."""
    return hashlib.sha256(f"snapshot:{tag}".encode("utf-8")).hexdigest()


def _digests_for(p, digests_base=None) -> dict:
    """Verified digests for every ACQUIRE and CARRY_FORWARD source of a plan."""
    if digests_base is not None:
        return dict(digests_base)
    return {s.source_id: _digest(s.source_id) for s in p.sources if s.action in ("ACQUIRE", "CARRY_FORWARD")}


def _build(p, digests=None, **overrides):
    """build_fingerprint with the plan's own non-source inputs (overridable to test refusals)."""
    inputs = p.planning_inputs or {}  # a blocked plan has none; the defaults only matter for the refusal test
    args = {"extractor_version": inputs.get("extractor_version", EXTRACTOR),
            "rule_schema_version": inputs.get("rule_schema_version", RULE_SCHEMA),
            "build_config": inputs.get("build_config", BUILD_CONFIG), "parent_release_id": inputs.get("parent_release_id")}
    args.update(overrides)
    return pl.build_fingerprint(p, _digests_for(p, digests), **args)


def _changed_plan(state=None):
    """Community 17.0 changed; every other source carried; no Enterprise token (Enterprise sources skipped)."""
    state = state or installed()
    return plan(check(c_over={"17.0": sha("c2", "17.0")}), state, last_inputs=previous_inputs(state))


class PlanShapeTests(unittest.TestCase):
    def test_redistribution_is_on_the_planned_source_not_the_spec(self):
        srcs = by_id(plan(check(ent_status="OK"), InstalledState(), token=True))
        self.assertEqual(srcs["odoo-community-17.0"].redistribution, "PUBLIC")
        self.assertEqual(srcs["odoo-enterprise-17.0"].redistribution, "RESTRICTED")
        self.assertNotIn("redistribution", srcs["odoo-enterprise-17.0"].spec)
        self.assertEqual(srcs["odoo-enterprise-17.0"].to_dict()["redistribution"], "RESTRICTED")

    def test_plan_exposes_planning_names_only(self):
        p = plan(check(), InstalledState(), token=False)
        self.assertFalse(hasattr(p, "fingerprint"))
        self.assertFalse(hasattr(p, "fingerprint_inputs"))
        self.assertEqual(p.planning_inputs["snapshot_digests"], {})
        self.assertEqual(fp.FingerprintInputs(**p.planning_inputs).digest(), p.planning_fingerprint)

    def test_official_is_true_for_both_families_and_kinds_follow_the_catalog(self):
        p = plan(check(ent_status="OK"), InstalledState(), token=True)
        acquired = [s for s in p.sources if s.action == "ACQUIRE"]
        self.assertTrue(all(s.spec["official"] is True for s in acquired))
        kinds = {s.edition: s.spec["kind"] for s in acquired}
        self.assertEqual(kinds, {"community": "GIT_COMMUNITY", "enterprise": "GIT_ENTERPRISE"})

    def test_planning_fingerprint_is_stable_and_planning_form_only(self):
        p = plan(check(ent_status="OK"), InstalledState(), token=True)
        self.assertEqual(p.planning_inputs["snapshot_digests"], {})
        self.assertEqual(plan(check(ent_status="OK"), InstalledState(), token=True).planning_fingerprint,
                         p.planning_fingerprint)


class BuildFingerprintTests(unittest.TestCase):
    def test_deterministic_and_matches_the_stored_form(self):
        p = _changed_plan()
        self.assertEqual(_build(p), _build(p))
        fingerprint, inputs = _build(p)
        self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")
        self.assertEqual(fp.FingerprintInputs.from_dict(inputs).digest(), fingerprint)

    def test_digest_insertion_order_does_not_matter(self):
        p = _changed_plan()
        digests = _digests_for(p)
        reordered = dict(reversed(list(digests.items())))
        self.assertEqual(_build(p, digests), _build(p, reordered))

    def test_build_form_differs_from_the_planning_form(self):
        p = _changed_plan()
        fingerprint, inputs = _build(p)
        self.assertNotEqual(fingerprint, p.planning_fingerprint)
        self.assertTrue(inputs["snapshot_digests"])
        self.assertEqual(set(inputs["snapshot_digests"]), set(inputs["source_shas"]))

    def test_members_are_exactly_the_acquire_and_carry_sources(self):
        p = _changed_plan()
        _, inputs = _build(p)
        members = {s.source_id for s in p.sources if s.action in ("ACQUIRE", "CARRY_FORWARD")}
        self.assertEqual(set(inputs["source_shas"]), members)
        self.assertEqual(set(inputs["snapshot_digests"]), members)
        self.assertFalse(any(sid.startswith("odoo-enterprise-") for sid in members))

    def test_carried_digests_come_from_the_installed_release(self):
        base = installed()
        state = InstalledState(release_id="rel-1", digest="d" * 64, revisions=base.revisions,
                               snapshot_digests={sid: _digest("old:" + sid) for sid in base.revisions})
        p = _changed_plan(state)
        digests = {s.source_id: (_digest("new:" + s.source_id) if s.action == "ACQUIRE"
                                 else state.snapshot_digests[s.source_id])
                   for s in p.sources if s.action in ("ACQUIRE", "CARRY_FORWARD")}
        _, inputs = _build(p, digests)
        self.assertEqual(inputs["snapshot_digests"]["odoo-community-16.0"], _digest("old:odoo-community-16.0"))
        self.assertEqual(inputs["snapshot_digests"]["odoo-community-17.0"], _digest("new:odoo-community-17.0"))

    def test_refused_when_an_acquired_source_has_no_verified_digest(self):
        p = _changed_plan()
        digests = _digests_for(p)
        del digests["odoo-community-17.0"]
        with self.assertRaises(fp.FingerprintError):
            _build(p, digests)

    def test_refused_when_a_carried_source_has_no_digest(self):
        p = _changed_plan()
        digests = _digests_for(p)
        del digests["odoo-community-16.0"]
        with self.assertRaises(fp.FingerprintError):
            _build(p, digests)

    def test_refused_for_malformed_digests(self):
        p = _changed_plan()
        for bad in ("", "A" * 64, "a" * 63, "a" * 65, "g" * 64, None, 7, ["a" * 64]):
            with self.subTest(bad=bad):
                digests = _digests_for(p)
                digests["odoo-community-17.0"] = bad
                with self.assertRaises(fp.FingerprintError):
                    _build(p, digests)

    def test_refused_for_a_digest_outside_the_acquire_and_carry_set(self):
        p = _changed_plan()  # no token: Enterprise sources are SKIP
        digests = _digests_for(p)
        digests["odoo-enterprise-17.0"] = _digest("skipped")
        with self.assertRaises(fp.FingerprintError):
            _build(p, digests)

    def test_refused_for_a_blocked_plan(self):
        p = plan(check(), installed(valid=False), token=False)
        self.assertEqual(p.decision, "BLOCKED")
        with self.assertRaises(fp.FingerprintError):
            _build(p, {})

    def test_refused_when_a_non_source_input_differs_from_the_plan(self):
        p = _changed_plan()
        for overrides in ({"extractor_version": "2"}, {"rule_schema_version": "2"},
                          {"build_config": {"profile": "other"}}, {"parent_release_id": None}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(fp.FingerprintError):
                    _build(p, **overrides)

    def test_each_non_source_input_flips_the_build_fingerprint(self):
        state = installed()
        chk = check(c_over={"17.0": sha("c2", "17.0")})
        base = _build(plan(chk, state))[0]
        variants = {
            "extractor_version": plan(chk, state, extractor="2"),
            "rule_schema_version": plan(chk, state, rule="2"),
            "build_config": plan(chk, state, config={"profile": "other"}),
            "parent_release_id": plan(chk, installed(release_id="rel-2")),
        }
        for name, variant in variants.items():
            with self.subTest(name):
                self.assertNotEqual(_build(variant)[0], base)

    def test_build_refuses_a_digest_for_the_wrong_source_form(self):
        p = _changed_plan()
        digests = _digests_for(p)
        digests["odoo-community-17.0"] = digests["odoo-community-17.0"].upper()
        with self.assertRaises(fp.FingerprintError):
            _build(p, digests)


class NeedsBuildTests(unittest.TestCase):
    def _current(self):
        p = _changed_plan()
        _, inputs = _build(p)
        return p, inputs

    def test_same_inputs_need_no_build(self):
        _, inputs = self._current()
        stored = json.loads(json.dumps(inputs))
        self.assertEqual(pl.needs_build(inputs, stored), (False, []))

    def test_key_order_of_the_stored_record_does_not_matter(self):
        _, inputs = self._current()
        stored = dict(reversed(list(json.loads(json.dumps(inputs)).items())))
        self.assertEqual(pl.needs_build(inputs, stored), (False, []))

    def test_each_changed_input_is_named_exactly(self):
        _, inputs = self._current()
        cases = {
            "catalog_digest": lambda d: d.update(catalog_digest="0" * 64),
            "extractor_version": lambda d: d.update(extractor_version="2"),
            "rule_schema_version": lambda d: d.update(rule_schema_version="2"),
            "build_config": lambda d: d.update(build_config={"profile": "other"}),
            "parent_release_id": lambda d: d.update(parent_release_id="rel-2"),
            "source_shas": lambda d: d["source_shas"].update({"odoo-community-17.0": "e" * 40}),
            "snapshot_digests": lambda d: d["snapshot_digests"].update({"odoo-community-17.0": _digest("x")}),
        }
        for name, mutate in cases.items():
            with self.subTest(name):
                current = json.loads(json.dumps(inputs))
                mutate(current)
                self.assertEqual(pl.needs_build(current, inputs), (True, [name]))

    def test_none_or_malformed_previous_inputs_need_build(self):
        _, inputs = self._current()
        bad_previous = (
            None, "fingerprint", {}, {"junk": 1},
            {**inputs, "snapshot_digests": {}},  # the planning form is never a build record
            {**inputs, "snapshot_digests": {"odoo-community-16.0": _digest("x")}},  # source sets differ
            {**inputs, "snapshot_digests": {k: "bad" for k in inputs["snapshot_digests"]}},  # malformed digests
            {**inputs, "source_shas": {k: "f" * 41 for k in inputs["source_shas"]}},  # malformed SHAs
        )
        for previous in bad_previous:
            with self.subTest(previous=repr(previous)[:60]):
                self.assertEqual(pl.needs_build(inputs, previous), (True, [pl.NO_PREVIOUS_BUILD_INPUTS]))

    def test_planning_form_is_never_accepted_as_a_previous_build(self):
        p, inputs = self._current()
        self.assertEqual(pl.needs_build(inputs, p.planning_inputs), (True, [pl.NO_PREVIOUS_BUILD_INPUTS]))

    def test_planning_form_against_a_build_record_names_the_snapshot_digests(self):
        p, inputs = self._current()
        self.assertEqual(pl.needs_build(p.planning_inputs, inputs), (True, ["snapshot_digests"]))

    def test_plan_noop_is_not_a_build_noop(self):
        state = installed()
        p = plan(check(), state, last_inputs=previous_inputs(state))
        self.assertEqual(p.decision, "NOOP")
        self.assertEqual(pl.needs_build(p.planning_inputs, None), (True, [pl.NO_PREVIOUS_BUILD_INPUTS]))

    def test_invalid_current_inputs_are_refused(self):
        with self.assertRaises(fp.FingerprintError):
            pl.needs_build({"junk": 1}, None)


class CarriedSpecAndInstalledShaTests(unittest.TestCase):
    def test_carried_catalog_sources_carry_a_registry_valid_spec_at_the_installed_sha(self):
        state = installed(enterprise=ENTERPRISE)
        p = plan(check(ent_status="OK"), state, token=True, last_inputs=previous_inputs(state, token=True))
        carried = [s for s in p.sources if s.action == "CARRY_FORWARD" and s.spec]
        self.assertEqual({s.edition for s in carried}, {"community", "enterprise"})
        for s in carried:
            with self.subTest(s.source_id):
                self.assertEqual(s.installed_sha, state.revisions[s.source_id])
                self.assertEqual(s.spec["revision"], s.installed_sha)
                self.assertEqual(registry.validate_spec(s.spec, ALLOW), [])
                reg = registry.SourceRegistry(ALLOW)
                reg.add(s.spec)
                self.assertEqual(reg.get(s.source_id)["revision"], s.installed_sha)

    def test_acquire_spec_is_at_the_target_sha_and_installed_sha_is_recorded(self):
        state = installed()
        p = plan(check(c_over={"17.0": sha("c2", "17.0")}), state, last_inputs=previous_inputs(state))
        srcs = by_id(p)
        acq = srcs["odoo-community-17.0"]
        self.assertEqual(acq.action, "ACQUIRE")
        self.assertEqual(acq.target_sha, sha("c2", "17.0"))
        self.assertEqual(acq.spec["revision"], acq.target_sha)
        self.assertEqual(acq.installed_sha, sha("c", "17.0"))
        self.assertEqual(srcs["odoo-community-16.0"].installed_sha, sha("c", "16.0"))
        self.assertIn("installed_sha", acq.to_dict())

    def test_installed_sha_is_none_on_every_source_when_nothing_is_installed(self):
        p = plan(check(), InstalledState(), token=False)
        self.assertTrue(all(s.installed_sha is None for s in p.sources))
        self.assertTrue(all("installed_sha" in s.to_dict() for s in p.sources))

    def test_installed_source_absent_from_catalog_keeps_empty_spec_and_installed_sha(self):
        state = installed()
        revs = dict(state.revisions)
        revs["odoo-community-9.0"] = sha("c", "9.0")
        state = InstalledState(release_id="rel-1", digest="d" * 64, revisions=revs, valid=True)
        s = by_id(plan(check(), state, last_inputs=previous_inputs(state)))["odoo-community-9.0"]
        self.assertEqual(s.action, "CARRY_FORWARD")
        self.assertEqual(s.spec, {})
        self.assertEqual(s.installed_sha, sha("c", "9.0"))


if __name__ == "__main__":
    unittest.main()
