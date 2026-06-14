# space-map search infra

Meilisearch + Caddy, deployed via Portainer on the `infrastructure/data/` VM.

Caddy (config inlined in the compose `config`, so no host file needed) serves
HTTP on `:9750` and proxies to Meili: public surface is `/indexes/*/search`,
`/multi-search`, `/health`; everything else is VPN-only (`403` otherwise).
TLS and the public hostname are handled by a Cloudflare tunnel → `:9750`.

## Deploy

1. `cp .env.example .env` and fill it in. The master key never leaves the VM.
2. Bring up the stack in Portainer.
3. Point the Cloudflare tunnel at `http://<host>:9750`.
4. From the VPN, mint the frontend's search-only key once and bake it in at
   build time:

   ```
   MEILI_URL=https://search.example.com \
   MEILI_MASTER_KEY=$(grep MEILI_MASTER_KEY .env | cut -d= -f2) \
       uv run space-map-search search-key
   ```

## Indexing

From any host on the VPN. Reindex is atomic (load into `features_tmp`, then swap):

```
MEILI_URL=https://search.example.com \
MEILI_MASTER_KEY=<from .env> \
    uv run space-map-search push --indices features
```
