"""CLI entrypoint for the Meilisearch indexer.

Usage:

    space-map-search push [--indices features]
    space-map-search search-key
"""

import argparse
import logging
import logging.config
import sys
import tomllib
from pathlib import Path

from space_map_data.utils.paths import CONFIG_FILE, DATA_DIR, EXPORT_DIR

from .client import MeiliClient
from .config import MeiliConfig
from .indices import ALL as ALL_INDICES
from .pipeline.push import push_index
from .tokens import print_search_key


def _setup_logging() -> None:
    log_cfg = DATA_DIR / "logging.toml"
    if log_cfg.exists():
        with open(log_cfg, "rb") as f:
            logging.config.dictConfig(tomllib.load(f))
    else:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )


def _resolve_export_dir() -> Path:
    """Honour an override in config.toml ([search].export_dir), else use the default."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "rb") as f:
            cfg = tomllib.load(f)
        override = cfg.get("search", {}).get("export_dir")
        if override:
            return Path(override).expanduser()
    return EXPORT_DIR


def cmd_push(args: argparse.Namespace) -> int:
    config = MeiliConfig.from_env()
    client = MeiliClient(config)
    export_dir = Path(args.export_dir) if args.export_dir else _resolve_export_dir()
    requested = args.indices or list(ALL_INDICES.keys())
    unknown = [u for u in requested if u not in ALL_INDICES]
    if unknown:
        print(f"Unknown indices: {', '.join(unknown)}", file=sys.stderr)
        print(f"Available: {', '.join(ALL_INDICES.keys())}", file=sys.stderr)
        return 2
    for uid in requested:
        push_index(client, ALL_INDICES[uid], export_dir)
    return 0


def cmd_search_key(_: argparse.Namespace) -> int:
    config = MeiliConfig.from_env()
    print_search_key(MeiliClient(config))
    return 0


def cli() -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(prog="space-map-search")
    sub = parser.add_subparsers(dest="cmd", required=True)

    push = sub.add_parser("push", help="Reindex selected indices into Meili")
    push.add_argument(
        "--indices",
        nargs="+",
        choices=list(ALL_INDICES.keys()),
        help="Subset of indices to push (default: all)",
    )
    push.add_argument(
        "--export-dir",
        help="Override EXPORT_DIR (defaults to the project's standard location)",
    )
    push.set_defaults(func=cmd_push)

    sk = sub.add_parser("search-key", help="Print the scoped search-only API key")
    sk.set_defaults(func=cmd_search_key)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(cli())
