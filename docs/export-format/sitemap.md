# Sitemap — `seo/sitemap.xml`

A single, uncompressed [sitemap](https://www.sitemaps.org/protocol.html) listing
the URLs worth surfacing to search engines. The frontend proxies it on the app
host (`https://spacemap.co/sitemap.xml`) so the `<loc>` origin matches the
sitemap's own, and `robots.txt` points crawlers at that path.

## Selection rule

The full catalogue is ~1.6 M objects, but most are anonymous asteroids with no
unique content. An object earns a URL when it is any of:

- a **promoted type** — planet, dwarf planet, moon, or star (barycenters are
  excluded: they're math points, not pages);
- in the **curated promoted set** (`PROMOTED_EXTRA_IDS` — flagship probes,
  famous asteroids/comets);
- backed by a **Wikidata presence** at or above `SEO_SITELINKS_THRESHOLD`
  sitelinks (`constants/seo.py`, default 5 — at which ~99.9 % also carry a
  Wikipedia description, keeping thin pages out).

Every exported group (`/g/<slug>`) is included. This yields ~38 k URLs; raise
the threshold to trim the tail.

## URL shape

Canonical paths mirror `frontend/src/lib/state/url.ts`:

- objects → `/<type>/<id>/<name>` — type letter from the id prefix
  (`naif`→`b`, `spkid`→`s`, `norad_satcat`→`e`, `probe`→`p`, `extra`→`u`),
  `<name>` is `obj.name` percent-encoded like `encodeURIComponent`;
- groups → `/g/<slug>` — the slug is already descriptive, so no name segment.

`lastmod` is the export date (uniform — the export is when content last
changed). Above 45 k URLs the writer warns; splitting into a sitemap index
would then also need matching chunk routes in the frontend proxy.
