# space-map search infra

Meilisearch + Caddy reverse proxy. Sits on the same Debian VM as
`infrastructure/data/`, deployed via Portainer.

## What lives where

- `docker-compose.yaml` — Meili + Caddy services.
- `Caddyfile` — TLS termination, CORS for the Pages origin, public surface
  limited to `/indexes/*/search`, `/multi-search`, `/health`. Everything
  else (settings, keys, tasks, dumps, swap, metrics, document CRUD) is
  VPN-only.
- `.env.example` — fill in and copy to `.env` next to the compose file.

## Deploy

1. Point `SEARCH_DOMAIN` at the VPS IP (A record).
2. `cp .env.example .env` and fill it in. The master key never leaves
   the VPS.
3. Bring it up via Portainer (or `docker compose up -d` for first run).
4. From inside the VPN, generate the public search-only key once:

   ```
   MEILI_URL=https://search.example.com \
   MEILI_MASTER_KEY=$(grep MEILI_MASTER_KEY .env | cut -d= -f2) \
       uv run space-map-search search-key
   ```

   Bake the printed `key` field into the frontend at build time.

## Indexing

The indexer runs from a developer machine (or any host on the VPN):

```
MEILI_URL=https://search.example.com \
MEILI_MASTER_KEY=<from .env> \
    uv run space-map-search push --indices features
```

Reindex is atomic: docs go into `features_tmp`, then a swap promotes them
to `features` in one step.
