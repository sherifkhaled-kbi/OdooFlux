# Contract: SARIF 2.1.0 and Unified Diff Mapping

## SARIF

| SARIF | Source |
|---|---|
| `runs[0].tool.driver.name` | `OdooFlux` |
| `runs[0].tool.driver.version` | `tool_version` |
| `runs[0].tool.driver.rules[]` | one per rule ID seen: `id`, `shortDescription` (rule message), `helpUri` (first evidence URL), `properties.step`, `properties.evidence` |
| `results[]` | one per Finding with status `OPEN`, `NEEDS_REVIEW`, or `REJECTED` (fixed findings omitted, but included with `--sarif-include-fixed` as `kind: "pass"`) |
| `results[].level` | CRITICAL→`error`, WARNING→`warning`, INFO→`note` |
| `results[].locations[0].physicalLocation` | `artifactLocation.uri` relative to the module root's parent; `region.startLine/startColumn/endLine/endColumn` (1-based) |
| `results[].partialFingerprints.odoofluxFindingId` | `Finding.id` (stable) |
| `results[].properties` | `status`, `module`, `rejection_reason?` |
| `invocations[0].exitCode` | process exit code |

## Unified diff

- One file per run, `--diff <path>`. Headers are `--- a/<module>/<relpath>` and `+++ b/<module>/<relpath>`, relative to the parent of each module.
- Only kept edits (applied and validated). Rejected edits are excluded and listed in an index.
- The index `<path>.index.json` maps each hunk to `edit_ids` and `rule_ids`.
- Line endings and encoding follow the original file. A file without a final newline uses the standard `\ No newline at end of file` marker.
- Must apply with `patch -p1` from the parent directory (SC-003).
