"""Generate scoped API keys for the frontend.

Meili supports per-key action scoping. The frontend ships a key limited to
``search`` (querying) and ``stats.get`` (the idle "N entries in catalog"
count, which exceeds search's maxTotalHits cap); the master key never leaves
the indexer host.
"""

import json
import logging

from .client import MeiliClient

logger = logging.getLogger(__name__)

# Actions granted to the frontend key. stats.get backs catalogCount().
_FRONTEND_ACTIONS = ["search", "stats.get"]


def ensure_search_key(
    client: MeiliClient, *, description: str = "frontend-search"
) -> dict:
    """Return an existing frontend key matching *description*, else create one."""
    for key in client.raw.get_keys().results:
        if key.description == description and set(key.actions) == set(
            _FRONTEND_ACTIONS
        ):
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
            "actions": _FRONTEND_ACTIONS,
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
