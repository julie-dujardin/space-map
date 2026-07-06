# space-map search infra

Meilisearch + Caddy + cloudflared, deployed via docker-compose.

Caddy (config inlined in the compose `config`, so no host file needed) proxies
**search only** — `/indexes/*/search`, `/indexes/*/stats`, `/multi-search`,
`/health`; everything else returns `403`. It has no host port: the only public
path is the in-stack Cloudflare tunnel (which also terminates TLS) → `caddy:80`.

Admin (settings, keys, indexing) is Meili directly on `:9751`, protected by the
master key. It binds to `127.0.0.1`, forward it with:

```
ssh -L 9751:127.0.0.1:9751 <vps-tailnet-name>
```

then use `MEILI_URL=http://127.0.0.1:9751` while the session is open.

## Deploy

1. Create a remotely-managed tunnel (Zero Trust > Networks > Tunnels) with a
   public hostname routed to `http://caddy:80`, and copy its token.
2. `cp .env.example .env` and fill it in.
3. Bring up the stack.
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
