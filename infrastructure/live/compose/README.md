# space-map live infra

Two containers, deployed via docker-compose:

- `tracking` runs the scheduler's image as a poller (`space-map-tracking run`).
  It samples the DSN feed every minute, ESTRACK and the DSN bot less often, and
  writes `v1/activity.json` into the live tree (`space-map-live`).
- `deploy` ships that tree to the Workers static-assets project
  `space-map-live`, served at `live.spacemap.co`.

The deploy script, `wrangler.jsonc` and `_headers` are inlined in the compose
`configs`, so no host file is needed. Every minute the script copies the tree,
and deploys the copy when it differs from the last deploy that passed its
check. The check fetches `v1/activity.json` from `live.spacemap.co` and
compares it with the uploaded copy. A failed deploy is tried again 10 minutes
later.

The tracking service rewrites `activity.json` only when its content changes,
so a deploy means news. A new container deploys once at start.

## Deploy

1. Make an API token (My Profile > API Tokens > Create Token > Custom token)
   with the one permission Account > Workers Scripts > Edit.
2. `cp .env.example .env` and fill it in.
3. Bring up the stack. The first start downloads wrangler (about 350 MB, kept
   in the `home` volume), then deploys.
4. The first deploy makes the Worker, and its check fails: the domain is not
   bound yet. Add `live.spacemap.co` as a custom domain of `space-map-live`
   (Workers & Pages > space-map-live > Settings > Domains & Routes). The next
   try passes, or restart the container to try at once.
5. The logs then show `live deploy verified`.
