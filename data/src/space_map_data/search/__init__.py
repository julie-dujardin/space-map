"""Meilisearch indexer for space-map exported artifacts.

Reads from EXPORT_DIR (the same artifacts the frontend consumes), assembles
search documents per registered index, and pushes them to a remote Meili
instance with an atomic tmp-then-swap reindex.

Run via the ``space-map-search`` CLI.
"""
