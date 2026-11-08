# T025 review packet: steps 14-15 to 18-19 (2026-11-07)
Status: PREPARED FOR HUMAN REVIEW. Nothing here is a sign-off. `peer_reviewed` is false and no step is `RESEARCHED`; T025 in `tasks.md` is not marked.
## How to use
For each category row: reproduce at least one location of every linked evidence record from the record alone (open the pinned-SHA URL, check the line and excerpt), confirm the claim is no stronger than the excerpt, then fill the reviewer fields in the checklist. `PYTHONPATH=src python3 -m odooflux knowledge validate` must report errors=0 afterwards.
Verification status legend:
- **agent-verified (T025)**: `tools/verify_evidence.py` re-fetched every location at the pinned SHA with an empty cache (all OK) and the claim text was checked against the excerpts by an AI agent, see `evidence-verification.md`. Not an independent human review.
- **not re-verified in T025**: record exists and validates against the schema, but its locations were not re-fetched in this pass.
- NOT_ASSESSED: the category has no (or no sufficient) research; nothing may be claimed for it.
Open gaps that apply to every step: G-R-02 (Odoo Enterprise not accessed). Resolved gaps cited below are resolved at the scope stated in `gaps.json`, not wider.

## Step 14→15 (research_status RESEARCH_SEEDED, peer_reviewed False)
Revisions: 14.0 cc0060e889, 15.0 3a28e5b0ad. Step open gaps: G-R-01, G-R-04. Review-only: `t-raw` → `t-out` (escaping semantics)

| Category | Status | Linked evidence (V = agent-verified T025, U = not re-verified) | Gaps | Remains NOT_ASSESSED / not established |
|---|---|---|---|---|
| assets | RESEARCH_SEEDED | EV-123 (U), EV-327 (U), EV-328 (U), EV-329 (U), EV-330 (U), EV-415 (V), EV-416 (V), EV-427 (V) | G-R-02 (OPEN), G-R-05 (RESOLVED), G-R-18 (OPEN) | Only the located facts above; category not exhaustively researched |
| behavioural | NOT_ASSESSED | EV-015 (U) | G-R-02 (OPEN), G-R-01 (OPEN) | Behavioural/semantic equivalence (G-R-01 for 12-15) and runtime behaviour not assessed |
| javascript_owl | RESEARCH_SEEDED | EV-423 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| manifest_dependencies | RESEARCH_SEEDED | EV-124 (U), EV-125 (U), EV-425 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| python_orm | RESEARCH_SEEDED | EV-102 (U), EV-110 (U), EV-421 (V), EV-483 (V), EV-484 (V), EV-486 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| qweb | RESEARCH_SEEDED | EV-201 (U), EV-202 (U), EV-203 (U), EV-331 (U), EV-334 (U), EV-422 (V) | G-R-02 (OPEN), G-R-04 (OPEN) | Only the located facts above; category not exhaustively researched |
| rules | NOT_ASSESSED | none | G-R-02 (OPEN), G-R-01 (OPEN) | No rules-category research; rule files not reviewed in this packet |
| runtime | RESEARCH_SEEDED | EV-426 (V) | G-R-02 (OPEN) | Only python_requires per EV-426; other runtime facts not assessed |
| security | RESEARCH_SEEDED | EV-400 (V), EV-401 (V), EV-402 (V), EV-424 (V), EV-480 (V), EV-481 (V), EV-482 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| xml_views_data | RESEARCH_SEEDED | EV-420 (V), EV-490 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |

Seeded evidence for the step: EV-123, EV-124, EV-201, EV-202. Records not re-verified in T025 for this step: 15.

## Step 15→16 (research_status RESEARCH_SEEDED, peer_reviewed False)
Revisions: 15.0 3a28e5b0ad, 16.0 9f40bf622c. Step open gaps: G-R-04, G-R-21, G-R-22. Review-only: `fields_view_get` overrides

| Category | Status | Linked evidence (V = agent-verified T025, U = not re-verified) | Gaps | Remains NOT_ASSESSED / not established |
|---|---|---|---|---|
| assets | RESEARCH_SEEDED | EV-123 (U), EV-415 (V), EV-416 (V) | G-R-02 (OPEN), G-R-18 (OPEN) | Only the located facts above; category not exhaustively researched |
| behavioural | NOT_ASSESSED | EV-015 (U) | G-R-02 (OPEN) | Behavioural/semantic equivalence (G-R-01 for 12-15) and runtime behaviour not assessed |
| javascript_owl | RESEARCH_SEEDED | EV-390 (V), EV-393 (V), EV-395 (V), EV-488 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| manifest_dependencies | NOT_ASSESSED | EV-125 (U) | G-R-02 (OPEN) | Whole category NOT_ASSESSED; linked records are seeds only |
| python_orm | RESEARCH_SEEDED | EV-001 (U), EV-011 (U), EV-012 (U), EV-013 (U), EV-014 (U), EV-102 (U), EV-110 (U), EV-410 (V), EV-411 (V), EV-483 (V), EV-484 (V), EV-486 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| qweb | RESEARCH_SEEDED | EV-201 (U), EV-202 (U), EV-203 (U), EV-332 (U) | G-R-02 (OPEN), G-R-04 (OPEN) | Only the located facts above; category not exhaustively researched |
| rules | NOT_ASSESSED | none | G-R-02 (OPEN) | No rules-category research; rule files not reviewed in this packet |
| runtime | NOT_ASSESSED | none | G-R-02 (OPEN) | Whole category NOT_ASSESSED |
| security | RESEARCH_SEEDED | EV-400 (V), EV-401 (V), EV-402 (V), EV-480 (V), EV-481 (V), EV-482 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| xml_views_data | RESEARCH_SEEDED | EV-107 (U), EV-490 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |

Seeded evidence for the step: EV-013, EV-014, EV-107, EV-203. Records not re-verified in T025 for this step: 15.

## Step 16→17 (research_status RESEARCH_SEEDED, peer_reviewed False)
Revisions: 16.0 9f40bf622c, 17.0 9ef8d62331. Step open gaps: G-R-08, G-R-20, G-R-21, G-R-22. Review-only: Field `states=` → view modifiers (manual), `name_get` overrides, `_read_group` callers

| Category | Status | Linked evidence (V = agent-verified T025, U = not re-verified) | Gaps | Remains NOT_ASSESSED / not established |
|---|---|---|---|---|
| assets | RESEARCH_SEEDED | EV-415 (V), EV-416 (V) | G-R-02 (OPEN), G-R-18 (OPEN) | Only the located facts above; category not exhaustively researched |
| behavioural | NOT_ASSESSED | EV-111 (U) | G-R-02 (OPEN) | Behavioural/semantic equivalence (G-R-01 for 12-15) and runtime behaviour not assessed |
| javascript_owl | RESEARCH_SEEDED | EV-121 (U), EV-122 (U), EV-391 (V), EV-392 (V), EV-488 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| manifest_dependencies | RESEARCH_SEEDED | EV-125 (U), EV-417 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| python_orm | RESEARCH_SEEDED | EV-001 (U), EV-010 (U), EV-011 (U), EV-012 (U), EV-013 (U), EV-014 (U), EV-102 (U), EV-108 (U), EV-110 (U), EV-207 (U), EV-412 (V), EV-483 (V), EV-484 (V), EV-486 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| qweb | NOT_ASSESSED | EV-202 (U), EV-203 (U) | G-R-02 (OPEN) | Whole category NOT_ASSESSED; linked records are seeds only |
| rules | NOT_ASSESSED | none | G-R-02 (OPEN) | No rules-category research; rule files not reviewed in this packet |
| runtime | NOT_ASSESSED | none | G-R-02 (OPEN) | Whole category NOT_ASSESSED |
| security | RESEARCH_SEEDED | EV-400 (V), EV-401 (V), EV-402 (V), EV-480 (V), EV-481 (V), EV-482 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| xml_views_data | RESEARCH_SEEDED | EV-109 (U), EV-117 (U), EV-322 (U), EV-323 (U), EV-337 (U), EV-490 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |

Seeded evidence for the step: EV-011, EV-012, EV-108, EV-109, EV-110, EV-111, EV-117, EV-125, EV-207. Records not re-verified in T025 for this step: 21.

## Step 17→18 (research_status RESEARCH_SEEDED, peer_reviewed False)
Revisions: 17.0 9ef8d62331, 18.0 75d6abe597. Step open gaps: G-R-21, G-R-22. Review-only: `name_get`/`_name_search` overrides, `rpc` service users, `numbercall` semantics

| Category | Status | Linked evidence (V = agent-verified T025, U = not re-verified) | Gaps | Remains NOT_ASSESSED / not established |
|---|---|---|---|---|
| assets | RESEARCH_SEEDED | EV-415 (V), EV-416 (V) | G-R-02 (OPEN), G-R-18 (OPEN) | Only the located facts above; category not exhaustively researched |
| behavioural | NOT_ASSESSED | none | G-R-02 (OPEN) | Behavioural/semantic equivalence (G-R-01 for 12-15) and runtime behaviour not assessed |
| javascript_owl | RESEARCH_SEEDED | EV-120 (U), EV-121 (U), EV-122 (U), EV-392 (V), EV-394 (V), EV-396 (V), EV-488 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| manifest_dependencies | RESEARCH_SEEDED | EV-125 (U), EV-212 (U), EV-417 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| python_orm | RESEARCH_SEEDED | EV-001 (U), EV-004 (U), EV-008 (U), EV-009 (U), EV-010 (U), EV-011 (U), EV-012 (U), EV-102 (U), EV-104 (U), EV-105 (U), EV-106 (U), EV-108 (U), EV-118 (U), EV-208 (U), EV-413 (V), EV-414 (V), EV-483 (V), EV-484 (V), EV-486 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| qweb | NOT_ASSESSED | EV-335 (U) | G-R-02 (OPEN) | Whole category NOT_ASSESSED; linked records are seeds only |
| rules | NOT_ASSESSED | none | G-R-02 (OPEN) | No rules-category research; rule files not reviewed in this packet |
| runtime | NOT_ASSESSED | none | G-R-02 (OPEN) | Whole category NOT_ASSESSED |
| security | RESEARCH_SEEDED | EV-210 (U), EV-400 (V), EV-401 (V), EV-402 (V), EV-406 (V), EV-480 (V), EV-481 (V), EV-482 (V) | G-R-02 (OPEN), G-R-16 (RESOLVED) | Only the located facts above; category not exhaustively researched |
| xml_views_data | RESEARCH_SEEDED | EV-112 (U), EV-113 (U), EV-119 (U), EV-336 (U), EV-337 (U), EV-490 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |

Seeded evidence for the step: EV-008, EV-009, EV-010, EV-104, EV-105, EV-106, EV-112, EV-113, EV-118, EV-119, EV-120, EV-121, EV-210. Records not re-verified in T025 for this step: 26.

## Step 18→19 (research_status RESEARCH_SEEDED, peer_reviewed False)
Revisions: 18.0 75d6abe597, 19.0 58bb9591d4. Step open gaps: G-R-21. Review-only: `_sql_constraints` conversion, `@api.returns` callers, `read_group` overrides

| Category | Status | Linked evidence (V = agent-verified T025, U = not re-verified) | Gaps | Remains NOT_ASSESSED / not established |
|---|---|---|---|---|
| assets | RESEARCH_SEEDED | EV-415 (V), EV-416 (V) | G-R-02 (OPEN), G-R-18 (OPEN) | Only the located facts above; category not exhaustively researched |
| behavioural | NOT_ASSESSED | EV-007 (U), EV-115 (U) | G-R-02 (OPEN) | Behavioural/semantic equivalence (G-R-01 for 12-15) and runtime behaviour not assessed |
| javascript_owl | RESEARCH_SEEDED | EV-488 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| manifest_dependencies | RESEARCH_SEEDED | EV-125 (U), EV-212 (U), EV-417 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| python_orm | RESEARCH_SEEDED | EV-001 (U), EV-002 (U), EV-003 (U), EV-004 (U), EV-005 (U), EV-006 (U), EV-008 (U), EV-009 (U), EV-010 (U), EV-102 (U), EV-116 (U), EV-208 (U), EV-209 (U), EV-418 (V), EV-419 (V), EV-483 (V), EV-484 (V), EV-486 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |
| qweb | NOT_ASSESSED | EV-333 (U) | G-R-02 (OPEN) | Whole category NOT_ASSESSED; linked records are seeds only |
| rules | NOT_ASSESSED | none | G-R-02 (OPEN) | No rules-category research; rule files not reviewed in this packet |
| runtime | NOT_ASSESSED | none | G-R-02 (OPEN) | Whole category NOT_ASSESSED |
| security | RESEARCH_SEEDED | EV-114 (U), EV-400 (V), EV-401 (V), EV-402 (V), EV-403 (V), EV-404 (V), EV-405 (V), EV-480 (V), EV-481 (V), EV-482 (V) | G-R-02 (OPEN), G-R-10 (RESOLVED) | Only the located facts above; category not exhaustively researched |
| xml_views_data | RESEARCH_SEEDED | EV-119 (U), EV-204 (U), EV-487 (V), EV-490 (V) | G-R-02 (OPEN) | Only the located facts above; category not exhaustively researched |

Seeded evidence for the step: EV-002, EV-003, EV-004, EV-005, EV-006, EV-007, EV-102, EV-114, EV-115, EV-116, EV-119, EV-209. Records not re-verified in T025 for this step: 21.

## Findings the reviewer should know
- 14 records (EV-394, 400, 402, 403, 404, 410, 411, 416, 419, 420, 421, 422, 424, 425) were cut back in pass 1 and re-checked in pass 2; EV-394, EV-411, EV-416 needed further correction (see `evidence-verification.md`).
- Field-set claims (G-R-10) rest on class-body scans (EV-480..482): each located line is reproducible, the "exactly N fields" statement is the scan result.
- G-R-03/06/08/09/17 are RESOLVED only at the scope in `gaps.json`; e.g. Widget removal (EV-392/343) is path-level absence, not proof of no relocation.
- EV-324 description says 8 versions were checked but locates 3; EV-489 completes it.
- `legacy_disposition.json`: 9 needs-research rows remain (G-R-04, G-R-21, G-R-22). No rules were created from the new evidence.
- Categories with status NOT_ASSESSED must stay so until research exists; nothing in this packet upgrades them.

## Sign-off checklist (all fields intentionally empty)
For each step the reviewer ticks only after reproducing the evidence.

| Step | Category reviewed | Records reproduced (IDs) | Claims within excerpts? | Reviewer name | Qualification | Date | Decision (accept / revise / reject) | Notes |
|---|---|---|---|---|---|---|---|---|
| 14→15 | assets |  |  |  |  |  |  |  |
| 14→15 | behavioural |  |  |  |  |  |  |  |
| 14→15 | javascript_owl |  |  |  |  |  |  |  |
| 14→15 | manifest_dependencies |  |  |  |  |  |  |  |
| 14→15 | python_orm |  |  |  |  |  |  |  |
| 14→15 | qweb |  |  |  |  |  |  |  |
| 14→15 | rules |  |  |  |  |  |  |  |
| 14→15 | runtime |  |  |  |  |  |  |  |
| 14→15 | security |  |  |  |  |  |  |  |
| 14→15 | xml_views_data |  |  |  |  |  |  |  |
| 15→16 | assets |  |  |  |  |  |  |  |
| 15→16 | behavioural |  |  |  |  |  |  |  |
| 15→16 | javascript_owl |  |  |  |  |  |  |  |
| 15→16 | manifest_dependencies |  |  |  |  |  |  |  |
| 15→16 | python_orm |  |  |  |  |  |  |  |
| 15→16 | qweb |  |  |  |  |  |  |  |
| 15→16 | rules |  |  |  |  |  |  |  |
| 15→16 | runtime |  |  |  |  |  |  |  |
| 15→16 | security |  |  |  |  |  |  |  |
| 15→16 | xml_views_data |  |  |  |  |  |  |  |
| 16→17 | assets |  |  |  |  |  |  |  |
| 16→17 | behavioural |  |  |  |  |  |  |  |
| 16→17 | javascript_owl |  |  |  |  |  |  |  |
| 16→17 | manifest_dependencies |  |  |  |  |  |  |  |
| 16→17 | python_orm |  |  |  |  |  |  |  |
| 16→17 | qweb |  |  |  |  |  |  |  |
| 16→17 | rules |  |  |  |  |  |  |  |
| 16→17 | runtime |  |  |  |  |  |  |  |
| 16→17 | security |  |  |  |  |  |  |  |
| 16→17 | xml_views_data |  |  |  |  |  |  |  |
| 17→18 | assets |  |  |  |  |  |  |  |
| 17→18 | behavioural |  |  |  |  |  |  |  |
| 17→18 | javascript_owl |  |  |  |  |  |  |  |
| 17→18 | manifest_dependencies |  |  |  |  |  |  |  |
| 17→18 | python_orm |  |  |  |  |  |  |  |
| 17→18 | qweb |  |  |  |  |  |  |  |
| 17→18 | rules |  |  |  |  |  |  |  |
| 17→18 | runtime |  |  |  |  |  |  |  |
| 17→18 | security |  |  |  |  |  |  |  |
| 17→18 | xml_views_data |  |  |  |  |  |  |  |
| 18→19 | assets |  |  |  |  |  |  |  |
| 18→19 | behavioural |  |  |  |  |  |  |  |
| 18→19 | javascript_owl |  |  |  |  |  |  |  |
| 18→19 | manifest_dependencies |  |  |  |  |  |  |  |
| 18→19 | python_orm |  |  |  |  |  |  |  |
| 18→19 | qweb |  |  |  |  |  |  |  |
| 18→19 | rules |  |  |  |  |  |  |  |
| 18→19 | runtime |  |  |  |  |  |  |  |
| 18→19 | security |  |  |  |  |  |  |  |
| 18→19 | xml_views_data |  |  |  |  |  |  |  |

Step-level sign-off (complete only after every category row above for the step is decided):

| Step | peer_reviewed may be set to true? | research_status to set | Reviewer | Date | Signature |
|---|---|---|---|---|---|
| 14→15 |  |  |  |  |  |
| 15→16 |  |  |  |  |  |
| 16→17 |  |  |  |  |  |
| 17→18 |  |  |  |  |  |
| 18→19 |  |  |  |  |  |

Rule: `RESEARCHED` requires `peer_reviewed: true` (enforced by `matrix.refuse_overclaims`). Do not set either from this packet; a qualified independent reviewer does it after sign-off. Then tick T025 in `tasks.md`.
