# space-map search infra

Meilisearch + Caddy + cloudflared, deployed via docker-compose.

Caddy (config inlined in the compose `config`, so no host file needed) proxies
**search only** — `/indexes/*/search`, `/multi-search`, `/health`; everything
else returns `403`. It has no host port: the only public path is the in-stack
Cloudflare tunnel (which also terminates TLS) → `caddy:80`.

The page holds no lasting key. The frontend's Worker keeps the search-only key
and signs a tenant token with it at `/api/search-key`, good for one hour, which
Meili checks by itself. The Worker can ask for [proof of a person](#proof-of-a-person)
first.

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
5. Create a Turnstile widget (Turnstile > Add widget) in Managed mode, for the
   hostname the site is served from, with pre-clearance left off. Its sitekey
   is the Worker's `PUBLIC_TURNSTILE_SITEKEY` and its secret key the Worker's
   `TURNSTILE_SECRET`. Leave `TURNSTILE_REQUIRE` unset until the logs show
   proofs that hold, then set it to `search`.
6. Add a rate limiting rule (the zone > Security > WAF > Rate limiting rules)
   on `http.host eq "<the site's hostname>" and http.request.uri.path eq "/api/search-key"`:
   20 requests per 10 seconds per IP, block. A proof guards the key, not the
   asking for one; this does. A page load asks once at most.

A deployment that gave its pages `PUBLIC_MEILI_SEARCH_KEY` has one more step:
delete that key in Meili (`DELETE /keys/<uid>`, with the master key) once the
new build is live. Whoever holds it can search with it until then. A tab
still on the old build loses search until it reloads.

## Proof of a person

With `TURNSTILE_SECRET` set, `/api/search-key` checks the `proof` of a request
with Cloudflare: a Turnstile token, which the page makes when
`PUBLIC_TURNSTILE_SITEKEY` names a widget. `TURNSTILE_REQUIRE` says whether a
request without one that holds is refused, `403`:

| `TURNSTILE_REQUIRE` | a key request |
| --- | --- |
| unset | checked and logged |
| `search` | required |

- A token is good once and a key for an hour: an hour of search costs a
  challenge. Nothing shows unless Cloudflare wants a click and the proof is
  required: the page first asks for its key without the click, and shows the
  widget only when that is refused. The widget then shows in the search box
  the visitor has open, and with none open a toast says so, once a page load.
- A click that does not pass ends the proof. The visitor is told once, and
  the page asks again after 30 seconds.
- What has no built-in results waits for that click, `/random` too, behind a
  card that holds the widget. A key that is refused or cannot be had stops
  the wait: `/random` then draws uniformly, from the export alone.
- A page loads nothing of Cloudflare's until it searches: the search panel
  opened, or a list that pages through the index.
- A proof that cannot be checked gets its key: Cloudflare not answering in
  three seconds is logged as an error and costs the check, not search. No
  proof at all is never that.
- A secret Cloudflare does not know is not that either. With proof required,
  a request that brings a token gets a `503` and search stops, where passing
  for an outage would let every made-up token in. With nothing required it is
  logged as an error and refuses nobody.
- `TURNSTILE_REQUIRE` without `TURNSTILE_SECRET` is a `503` for every request:
  giving keys would leave open a door the settings say is shut.
- Every key given or refused without a proof that held is logged, `no proof of
  a person`, with why: what to read before requiring it. With nothing
  required, a visitor Cloudflare wants a click from is logged as `absent`.
  With proof required, the same visitor is logged as refused once, before
  the click.
- Without `TURNSTILE_SECRET` nobody is asked, and without the sitekey the page
  sends no proof.

Cloudflare's [test keys](https://developers.cloudflare.com/turnstile/troubleshooting/testing/)
work on localhost: `1x0000000000000000000000000000000AA` as the secret passes
every token, `2x0000000000000000000000000000000AA` none. The sitekey
`3x00000000000000000000FF` makes the widget ask for a click.

## Indexing

Against Meili directly:

```
MEILI_URL=http://<host>:9751 \
MEILI_MASTER_KEY=<from .env> \
    uv run space-map-search push
```
