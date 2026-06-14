# space-map search infra

Meilisearch + Caddy, deployed via Portainer on the `infrastructure/data/` VM.

Caddy (config inlined in the compose `config`, so no host file needed) serves
HTTP on `:9750` and proxies **search only** — `/indexes/*/search`,
`/multi-search`, `/health`; everything else returns `403`. TLS and the public
hostname come from a Cloudflare tunnel → `:9750`.

Admin (settings, keys, indexing) is Meili directly on `:9751`, protected by the
master key. Reach it over the LAN/Tailscale — it's never exposed publicly.

## Deploy

1. `cp .env.example .env` and fill it in. The master key never leaves the VM.
2. Bring up the stack in Portainer.
3. Point the Cloudflare tunnel at `http://<host>:9750`.
4. Mint the frontend's search-only key once and bake it in at build time:

   ```
   MEILI_URL=http://<host>:9751 \
   MEILI_MASTER_KEY=$(grep MEILI_MASTER_KEY .env | cut -d= -f2) \
       uv run space-map-search search-key
   ```

## Indexing

Against Meili directly. Reindex is atomic (load into `features_tmp`, then swap):

```
MEILI_URL=http://<host>:9751 \
MEILI_MASTER_KEY=<from .env> \
    uv run space-map-search push
```
