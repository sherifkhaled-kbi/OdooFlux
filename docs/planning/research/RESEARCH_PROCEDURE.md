# Research and refresh procedure (implementers)

Scope: producing one evidence record, adding a version, and refreshing pinned evidence. Everything
here runs offline except the clone step. Commands assume the repository root.

## 1. Clone the pinned revisions (once per machine)

The pinned SHAs are in `src/odooflux/knowledge/official_sources/revisions.json`. Use blob-filtered
partial clones so only the trees and the blobs you read are downloaded:

```bash
mkdir -p /tmp/odoo-pins && cd /tmp/odoo-pins
for branch in 17.0; do
  sha=$(python3 -c "import json;print(next(r['revision'] for r in json.load(open('$OLDPWD/src/odooflux/knowledge/official_sources/revisions.json')) if r['repository']=='odoo/odoo' and r['branch']=='$branch'))")
  git init -q odoo-$branch && cd odoo-$branch && git remote add origin https://github.com/odoo/odoo
  git fetch -q --depth 1 --filter=blob:none origin "$sha" && cd ..
done
```

Repeat with `https://github.com/odoo/documentation` for documentation evidence. A fetch takes about
15 seconds and a few megabytes per pinned commit.

## 2. Produce one evidence record

1. Find the claim in the source at the pinned SHA: `git -C odoo-17.0 show <sha>:<path> | grep -n "<token>"`.
   Record the 1-based line and the exact text of that line.
2. Create `src/odooflux/knowledge/evidence/EV-NNN.json` (next free number). Fill every field of the
   evidence schema (`knowledge/schemas/evidence.schema.json`). `url` must start with an allow-list prefix
   (`official_sources/allow_list.json`). `revision` must be a 40-hex SHA in `revisions.json`.
3. For an absence claim, use `kind: "absent"`, `line: null`, and a `search_scope`. Confirm the token is not
   in the scope at the pinned SHA.
4. Validate: `python3 odooflux.py knowledge validate` must report `errors=0`.

## 3. Add a version (data only)

Add the version to `compatibility/versions.json` with `python_min` (EV-125 style evidence), add the
transition with `research_status: NOT_ASSESSED`, and add `compatibility/<from>-<to>.research.json` with the
per-category status. The planner blocks the step until its status is researched (or `--allow-unverified`).

## 4. Refresh evidence against new revisions

```bash
python3 odooflux.py knowledge refresh --repo odoo/odoo=/tmp/odoo-pins/odoo-17.0 \
    --revision 17.0=<new-sha> --report /tmp/refresh.json
```

Read the report: `unchanged`, `moved` (new line proposed), `missing` (match text gone; candidates listed),
or `unavailable` (revision not in the clone). Dry-run is the default. Review, then add `--apply` to write
moved lines and set missing records to `CONFLICTING` (their rules are capped to `DETECT_ONLY`).

## 5. Regenerate the matrix

```bash
python3 odooflux.py knowledge matrix           # writes docs/planning/VERSION_COMPATIBILITY_MATRIX.md
python3 odooflux.py knowledge matrix --check   # exit 1 if the committed file is stale
```

Peer check: a second person follows sections 1–2 for one record and reports the same line and text.
