"""Source acquisition for the knowledge acquisition pipeline (feature 011, P4).

Modules: `sources` (registry and status machine), `blobstore` (content-addressed blobs), `snapshot` (snapshot
builder). Adapters live in `adapters/` and register through `sources.register_adapter`.
"""
