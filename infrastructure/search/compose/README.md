# space-map search infra

Meilisearch + Caddy + cloudflared, deployed via docker-compose.

Caddy (config inlined in the compose `config`, so no host file needed) proxies
**search only** — `/indexes/*/search`, `/multi-search`, `/health`; everything
else returns `403`. It has no host port: the only public path is the in-stack
Cloudflare tunnel (which also terminates TLS) → `caddy:80`.

The page holds no lasting key. The frontend's Worker keeps the search-only key
and signs a tenant token with it at `/api/search-key`, good for one hour, which
Meili checks by itself.

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
4. Mint the search-only key once:

   ```
   MEILI_URL=http://<host>:9751 \
   MEILI_MASTER_KEY=$(grep MEILI_MASTER_KEY .env | cut -d= -f2) \
       uv run space-map-search search-key
   ```

   Its `key` and `uid` are the secrets `MEILI_SEARCH_KEY` and
   `MEILI_SEARCH_KEY_UID` of the frontend's Worker, set in the Cloudflare
   dashboard beside `PUBLIC_MEILI_URL`. `PUBLIC_MEILI_SEARCH_KEY` stays unset:
   a page that has it searches with it and asks the Worker for nothing.
A deployment that gave its pages `PUBLIC_MEILI_SEARCH_KEY` has one more step:
delete that key in Meili (`DELETE /keys/<uid>`, with the master key) once the
new build is live. Whoever holds it can search with it until then. A tab
still on the old build loses search until it reloads.

## Indexing

Against Meili directly:

```
MEILI_URL=http://<host>:9751 \
MEILI_MASTER_KEY=<from .env> \
    uv run space-map-search push
```
