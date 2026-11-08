# acl_missing_model

Adds an access row (`model_odooflux_missing`) for a model that no module defines.

- Expected L4 result: `FAIL`, status `FAILED`.
- Expected error class: `access_rights` (`External ID not found in the system` while loading
  `security/ir.model.access.csv`, EV-365; classified by the `ir.model.access` context).
