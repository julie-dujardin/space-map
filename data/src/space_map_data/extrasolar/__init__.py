"""Stable IDs and record tables for the objects outside the solar system.

- `ids`: the ID layout, serial·2^29 + table·2^24 + cell.
- `sky`: HEALPix cells, sky regions and disc searches.
- `tables`: the table definitions and the merge by source order.
- `registry`: the append-only registry and the table store.
- `match`: cross-catalogue matching by position.
- `engine`: one ingest run, from catalogue rows to committed IDs and tables.
"""
