# Knowledge Base Backlog

Status: PROPOSAL, created with [FRAMEWORK_COMPLETION_PLAN.md](FRAMEWORK_COMPLETION_PLAN.md), pending owner decision OD-1. Written 2026-11-07.

Nothing here is removed or cancelled. These items are deferred until the framework gate passes, and each one keeps its original task ID. The existing KB (200 evidence records, 91 rules, matrix, view index, 42 golden review cases) stays intact.

## Rules for working this backlog
- Start only after the framework completion gate, or in a session that touches no framework file.
- Evidence must come from official sources at pinned SHAs and pass `tools/verify_evidence.py`. No invented evidence.
- New rules start DETECT_ONLY. Promotion to FIX_ENABLED or AUTO_TRANSFORM needs evidence, independent review and owner approval.
- Independent review requirements are unchanged. Agents never mark golden outputs or peer reviews approved.
- Every item ends with `knowledge validate`, `matrix --check` and the full suite passing.

## Backlog

Priority: P-high = unblocks wider support claims; P-med = coverage; P-low = nice to have.

| ID | Origin (task / gap) | Item | Needs | Priority |
|---|---|---|---|---|
| KB-006-T025r | 006 T025 | Peer review of research records for steps outside the validation path (14-15, 15-16, 16-17, 18-19, and 17-18 records not cited by the minimal corpus); set `peer_reviewed` and `RESEARCHED` where complete | Human reviewer; packet `T025-review-packet.md` | P-high |
| KB-006-T035r | 006 T035 | Golden expected trees for 17.0 to 19.0 and any 17.0 module beyond `kbi_demo` | Independent review | P-high |
| KB-006-T044r | 006 T044 | Golden expected trees for sources 14.0, 15.0, 16.0 to each later target | Independent review; 42 cases in `knowledge/golden_corpus/review/` | P-high |
| KB-006-T059r | 006 T059 | Full quickstart run recorded for all paths | KB-006-T035r, KB-006-T044r | P-med |
| KB-008-T029r | 008 T029 | Mark `RUNTIME_VALIDATED` for targets other than the validation path, one per passing recorded runtime run | Docker runs; image source for 17.0 and below (G-R-21) | P-med |
| KB-006-SC002 | 006 SC-002 | Bring steps 14-15 to 18-19 to `RESEARCHED` and `RULES_TESTED` in the matrix | KB-006-T025r | P-high |
| KB-006-SC003 | 006 SC-003 | Byte-match golden migrations for all in-scope pairs | KB-006-T035r, KB-006-T044r | P-high |
| KB-002-FIX | 002 T011, T012, T013, T014, T016 | Fixtures `v12_kbi_legacy`, `v13_kbi_sudo`, `v15_kbi_assets`, `v16_kbi_views`, `v18_kbi_orm` with EV references | Per 002 research R-03 | P-med |
| KB-002-T015 | 002 T015 | `v17_kbi_owl` fixture, if the 17.0 fixture used for the validation path does not already carry the OWL `rpc` construct | EV-120 | P-low |
| KB-006-G01 | 006 gap G-R-01 | Source-diff research for steps 12-13, 13-14, 14-15 (partly covered by EV-420..427) | Official source research | P-med |
| KB-006-G04 | 006 gap G-R-04 | QWeb directive changes (`t-esc`, `t-raw`, `t-out`) beyond presence counts | Official source research | P-med |
| KB-006-G18 | 006 gap G-R-18 | Backend CSS class changes per version (only `.o_form_sheet_bg`, `.o_list_view` researched) | Official source research | P-med |
| KB-006-G21 | 006 gap G-R-21 | Whether chatter fields and `widget="mail_thread"` in form view arch remain valid per version | Official source research | P-med |
| KB-008-IMG | 008 gap G-R-21 (008 numbers its gaps separately from 006) | Image source for versions up to 17.0 (repository history vs build from pinned source) | Decision plus runtime work | P-high |
| KB-006-G22 | 006 gap G-R-22 | View-arch claims without official evidence (`<chatter/>` placement, `<header>` placement) | Official source research | P-med |
| KB-006-SUCC | 006 T068, T075 (D-A6) | Successors for the other 234 of 236 removed modules; `replaced_by` only with evidence | Official source research | P-med |
| KB-006-FIELD | 006 T066, T074 (D-A4/D-A5) | `acquirer_id` field rename, table renames, ACL row ids, unqualified ids (all evidenced or noted as unmapped) | Model-aware detection design | P-med |
| KB-006-D-A3 | D-A3 (not approved) | Automatic version-prefix rewriting | Owner approval, evidence, review | P-low |
| KB-006-D-A5 | D-A5 (not approved) | Automatic renamed-model transforms | Owner approval, evidence, review | P-low |
| KB-006-LEG | legacy disposition | Nine `needs-research` legacy rules; re-verify the 35 retired and 23 corrected entries as research progresses | Official source research | P-med |
| KB-006-VIEW | 006 T069, T076, T077 | Extend the view index to non-core modules and measure XPath coverage; an unavailable index stays INFO | Index size budget (5 MB total per version set) | P-low |
| KB-006-MAT | matrix | Expand version coverage beyond transitions 12 to 19 as new Odoo versions appear, using the documented add-version procedure | Official source research | P-low |
| KB-006-GC | golden corpus | Decide fate of the 42 pending review cases (approve, reject, or retire) | Independent human review | P-high |
| KB-010-SUP | 010 T007 | Grow the support statement as each path gains `RULES_TESTED` and `RUNTIME_VALIDATED` | KB-006-SC002, KB-008-T029r | P-med |
| KB-007-BM | 007 T032 | Extend the AI benchmark corpus beyond the minimal templates | Needs KB-006-SC003 | P-low |

## Traceability index

| Original task or gap | Backlog ID | Framework counterpart |
|---|---|---|
| 006 T025 | KB-006-T025r | T025-min |
| 006 T035 | KB-006-T035r | T035-min |
| 006 T044 | KB-006-T044r | none (fully deferred) |
| 006 T059 | KB-006-T059r | T059-min |
| 006 SC-002, SC-003 | KB-006-SC002, KB-006-SC003 | framework gate scope note (A-4) |
| 008 T029 | KB-008-T029r | T029-gen, T029-data |
| 002 T010-T016 | KB-002-FIX, KB-002-T015 | FC-0.1 keeps v14 and one 17.0 fixture |
| 008 T002 / 008 G-R-21 | KB-008-IMG | runtime check on the 18.0 target |

## Open question carried over
`REQ-MAN-002` wording ("unless opts out") is a framework decision (OD-4), not backlog.
