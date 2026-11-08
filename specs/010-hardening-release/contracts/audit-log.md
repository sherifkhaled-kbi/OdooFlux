# Contract: Audit Log

Location: `<state-dir>/runs/<run-id>/log/audit.jsonl` (append-only JSON Lines; refused if inside a scanned path). It sits in `log/` rather than the run root because analysis and dry runs may create only `state.json` and `log/` (TST-003-030); the contract path was changed for that reason (register item WSG-06).

Entry fields: `ts` (UTC ISO-8601), `run_id`, `seq` (monotonic), `actor` (`tool`), `action`, `target` (path or resource, relative where possible), `outcome` (`ok`, `failed`, `refused`), `details` (object; never contains secrets or file contents), `prev_hash` (sha256 of the previous line, giving tamper evidence).

Actions: `config_loaded`, `plan_created`, `workspace_created`, `backup_created`, `backup_verified`, `file_written`, `file_promoted`, `edit_rejected`, `rollback_started`, `rollback_completed`, `checkpoint_written`, `ai_request` (provider, model, token counts, cache hit; no prompt text), `runtime_launched`, `runtime_teardown`, `report_written`, `run_finished`, and `module_blocked` (added in P9: a blocked module is a consequential outcome).

Limit: the chain proves that no entry was edited, deleted or reordered before another entry; a change to the final line alone is not detectable. `run_finished` closes a normal run.

Redaction: values matching configured secret names, or credential-shaped patterns, are replaced by `***`. A test with canary secrets enforces this (REQ-AI-008).
