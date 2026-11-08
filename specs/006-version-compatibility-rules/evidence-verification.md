# Evidence verification (T025 partial pass, 2026-11-07, second pass)

Scope: EV-390..396, EV-400..406, EV-410..419, EV-420..427 (32 records; the first pass wrote "40", the ranges contain 32) plus the new records EV-480..EV-490 (11). Method: `tools/verify_evidence.py` re-fetches raw.githubusercontent.com at the cited SHA, checks SHA == pinned SHA in `official_sources/revisions.json`, excerpt present at the cited line (whitespace-normalised), and absence claims (404 or no match). Claim support is judged by reading. Set `EV_CACHE=<empty dir>` to force a fresh fetch (second pass used an empty cache; 62 files fetched for the 14 revised records alone).

This is an agent pass, not independent human peer review. `peer_reviewed` stays false and no step is RESEARCHED.

## Pass 1 (first pass, unchanged)
219 locations OK after one defect fix (absent regexes stored as `^s+` were vacuous, now `^\s+`). 14 records had overreaching claims and were cut back: EV-394, 400, 402, 403, 404, 410, 411, 416, 419, 420, 421, 422, 424, 425. The other 18 of the 32 were VERIFIED as written.

## Pass 2 (independent re-verification of the 14 revised records)
- Mechanical, fresh fetch (empty cache): 128/128 locations OK for the 14 records (0 BAD_REVISION, 0 EXCERPT_MISMATCH, 0 ABSENT_FAIL).
- Claim vs excerpt, record by record, found three residual overreaches in the trimmed text, now corrected:
  - EV-394: "at 18.0-19.0 ormService has no dependencies and imports rpc" was located only at 18.0. Added the 19.0 import line and the 19.0 absence of `dependencies:` as locations (both exist in the pinned source).
  - EV-411: "16.0-19.0 have a Dispatcher class" was located only at 16.0 and 19.0. Added 17.0 and 18.0 `class Dispatcher(ABC):` locations.
  - EV-416: "selector is defined" overstated 16.0-19.0, where only `.o_list_view &` (a qualified use) is located; wording changed to "appears as a selector" and the notes say so.
- The other 11 trimmed records (EV-400, 402, 403, 404, 410, 419, 420, 421, 422, 424, 425) are strictly supported by their located excerpts. EV-403's "color not defined at 19.0" and "no `users`/`category_id`" rest on absence regexes that pass; its "color present at 14-18" is not claimed.
- Full set after corrections: 32 records, 223 locations, all OK on fresh fetch.

## New evidence (EV-480..EV-490), all 357 locations OK on fresh fetch
- EV-480/481/482 (G-R-10): field-name sets of ir.model.access (8), ir.rule (9 + stored computed `global`) at 12.0-19.0, and res.groups at 12.0-18.0. Sets come from a class-body scan; each field line is re-verifiable, the "exactly N" completeness is the scan result, not mechanically re-verifiable. Attributes, labels and defaults are not compared.
- EV-483 (_inherits), EV-484 (Selection lambda default), EV-485 (old-API cr/uid), EV-486 (Char size), EV-487 (ir.ui.view groups_id to group_ids at 19.0), EV-488 (OWL useRef), EV-489 (`<url>` tag), EV-490 (list RNG `editable`): see each record's notes for scope limits.
- Finding for the owner of EV-324 (outside this pass): its description says "all 8 checked" but its locations cover only 12.0, 13.0 and 19.0; EV-489 completes the 8 versions. EV-324 was not edited.

## G-R-10
Now RESOLVED at field-name level only (EV-480..482, 487 plus EV-345/347/401/403..406/424). Field attributes, labels, defaults and behaviour are explicitly not established (see gap text). G-R-01, G-R-18 stay OPEN. New OPEN gaps: G-R-21 (message_ids/activity_ids/message_follower_ids/mail_thread in form arch), G-R-22 (`<chatter/>` placement, `<header>` 17.0, `<notebook invisible>` 18.0, web_client_action).

## Traceability
Rules citing EV-39x..42x still match their evidence. `knowledge validate`: records=174 errors=0 warnings=0; matrix regenerated from the research files (stale resolved gaps G-R-03/10/11 removed from step `open_gaps`; G-R-21/22 added).

## legacy_disposition.json (68 entries)
Re-dispositioned from the 16 stale/needs-research rows, using verified evidence only (9 moved, 7 still needs-research with an open gap):
- retire: XML#1 (EV-320/321: `<openerp>` accepted 12.0-19.0), JS J6 (EV-488/341).
- correct: PYTHON#3 (EV-485), PYTHON#4 (EV-486), XML#6 (EV-324/489), XML#7 (EV-114/405/487), XML#13 (EV-336/337, window is 17-18 not 16+), JS J2 (rule 16-17.js.odoo-define-legacy-form), JS J3 (rule 17-18.js.legacy-widget-removed, path-level absence). J1 also refreshed.
- needs-research: PYTHON#14 (G-R-04), XML#8 and #18 (G-R-22), XML#14-#17 (G-R-21).
The five retirements without evidence: PYTHON#7 now cites EV-483 and PYTHON#22 EV-484 (retire kept); XML#10 stays retire citing EV-490 plus audit finding F-VER-3 (regex does not match its claim; cited as an audit finding, not Odoo evidence); XML#21 and V18-4 were unsupported as retirements (no official evidence found) and are now needs-research under G-R-22.
Totals: keep 1, correct 23, retire 35, needs-research 9. No new rules were created; no `*.rules.json` edited.

## T025
Acceptance (reviewer reproduces >= 1 location per record; step status updated) is NOT met: no independent qualified reviewer, every step 14-15..18-19 still has NOT_ASSESSED / RESEARCH_SEEDED categories. Review packet: `T025-review-packet.md`. T025 is not marked done.
