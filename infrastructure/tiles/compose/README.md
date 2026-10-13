# space-map tiles infra

Caddy, deployed via docker-compose.

Caddy (config inlined in the compose `config`, so no host file needed) serves
the [surface tiles](../../../docs/export-format/tiles.md) from the tile tree,
which it mounts read-only: `/v1/tiles/…/{y}.webp` and nothing else. The stack
has no tunnel of its own. The public path is the Cloudflare tunnel of the
[homelab](https://github.com/julie-dujardin/homelab) (`compose/cloudflared`,
which also terminates TLS) → host port `9752`. Cloudflare's edge cache is in
front of the tunnel.

There is no upload. Ingest writes the pyramids into the tree that Caddy
serves.

## Deploy

1. `cp .env.example .env` and fill it in.
2. Bring up the stack.
3. Add a public hostname to the homelab tunnel (Zero Trust > Networks >
   Tunnels), routed to `http://<host>:9752` as the other homelab services
   are.
4. Turn on Smart Tiered Cache (the zone > Caching > Tiered Cache). One data
   centre then asks the server for a tile, and the others ask that one.
5. Check the host, from a machine that has the tile tree:

   ```
   TILES_URL=https://<public hostname> ../check.sh
   ```

6. Set `PUBLIC_TILES_URL` to the public hostname on the frontend's Worker, in
   the Cloudflare dashboard. Unset, the site draws the whole-globe tiers
   alone.

The zone needs no cache rule. Cloudflare caches `.webp` by default, for as
long as the `Cache-Control` of the tile says: a year. The query string is part
of its cache key, so the `?v=` token of a rebuilt pyramid makes a new entry. A
rule that ignores the query string would break that.

## What the edge keeps

The edge is a cache, not a store. A data centre drops the tiles that are asked
for least when it needs room, whatever their age, and Cloudflare states no
time for that. A tile that few people look at comes from the server again.

When the server is off:

- A tile that the edge holds is served.
- Any other tile fails: error 1033 with the tunnel down, `502` with only Caddy
  down. The edge does not keep these errors, so tiles come back with the
  server.
- A page that gets four failures in a row draws the tiers until it is
  reloaded.

## A rebuild is public when it ends

Ingest builds a pyramid aside (`{id}.building`) and a patch aside
(`.patch-{id}`), neither served, and puts each in place at the end. The
export still names the version before that one. Until the export is
deployed, a page asks for the new tiles with the old `?v=`, and the edge
keeps them under it. For a height pyramid with a new range, those heights
are wrong. Deploy the export soon after a rebuild.

Between the removal of the old folder and the rename of the new one the
pyramid is absent, and the edge keeps a `404` for three minutes.
