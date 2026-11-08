# Golden corpus (inputs only)

`manifest.json` pins small, real addons from official `odoo/odoo` (versions 14.0-17.0) by commit
SHA (matching `src/odooflux/knowledge/official_sources/revisions.json`), with a sha256 per file.
OCA repositories are skipped: no pinned commit SHA was resolved.

    python3 tools/fetch_golden_corpus.py [DEST]          # default /tmp/odooflux-golden-corpus
    python3 tools/fetch_golden_corpus.py --check [DEST]  # offline sha256 verification

**These are inputs only.** Expected outputs are NOT generated. They require human review, and
that review blocks spec 006 T035/T044. Nothing is written under `tests/`.
