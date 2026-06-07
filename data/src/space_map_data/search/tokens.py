"""Generate scoped search-only API keys for the frontend.

Meili supports per-key action scoping. The frontend ships a key whose only
permission is ``search``; the master key never leaves the indexer host.
"""

import json
import logging

from .client import MeiliClient

logger = logging.getLogger(__name__)


def ensure_search_key(
    client: MeiliClient, *, description: str = "frontend-search"
) -> dict:
    """Return an existing search-only key matching *description*, else create one."""
    for key in client.raw.get_keys().results:
        if key.description == description and list(key.actions) == ["search"]:
            return {
                "uid": key.uid,
                "key": key.key,
                "description": key.description,
                "actions": list(key.actions),
                "indexes": list(key.indexes),
            }
    created = client.raw.create_key(
        {
            "description": description,
            "actions": ["search"],
            "indexes": ["*"],
            "expiresAt": None,
        }
    )
    return {
        "uid": created.uid,
        "key": created.key,
        "description": created.description,
        "actions": list(created.actions),
        "indexes": list(created.indexes),
    }


def print_search_key(client: MeiliClient) -> None:
    info = ensure_search_key(client)
    print(json.dumps(info, indent=2))
