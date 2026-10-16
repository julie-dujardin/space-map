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
- backed by a **Wikidata presence** at or above `SITELINKS_THRESHOLD`
  (`export/sitemap.py`, default 5 — at which ~99.9 % also carry a Wikipedia
  description, keeping thin pages out).

An object the export leaves out has no page and is not listed. Every exported
group is included.

**Surface features** clear the same sitelink floor, counted on the feature's own
Wikidata entity: 3.5 k of the 9 k features that have a QID, out of a 16 k
gazetteer. The rest are anonymous craters whose page would be a name and a
coordinate. A feature the gazetteer does not export (no position or no type
code) is not listed: its page would answer 404. Together this yields ~42 k
URLs; raise the threshold to trim the tail.

## URL shape

A page states its canonical link with the name the app gives it in the base
locale, and the sitemap must list that same URL. So each path carries that
name, read from the files the app reads it from. The paths follow
`frontend/src/lib/state/page-href.ts` and the names
`frontend/src/lib/state/page-name.ts`:

- objects → `/<type>/<id>/<name>` — type letter from the id prefix
  (`naif`→`b`, `spkid`→`s`, `norad_satcat`→`e`, `probe`→`p`, `extra`→`u`),
  `<name>` is the name of the object's base-locale bundle entry, else that of
  its `__global__` entry;
- groups → `/g/<slug>/<name>` — `<name>` is the name of the group's
  base-locale bundle entry. A category (`cat-…`) takes the app's own label
  (`category_name_*` in `frontend/messages`), and so does an orbit class the
  export does not name (`orbit_class_*`);
- features → `/<type>/<id>/f/<featureId>/<name>` — `<type>/<id>` is the host
  body, `<name>` is the feature's line in the base-locale label file, which is
  the IAU `name`.

Every name is percent-encoded like `encodeURIComponent`. A page with no name
has no name segment, and the writer warns about a group in that case: its page
calls itself by a name the sitemap cannot give.

The names come from the bundles, so `space-map-export --only seo` rewrites
the file from an export that is already there, with the page records below.

Each of these pages builds its own SSR title/description/OG card in
`frontend/src/lib/seo/meta.ts`. A feature's description is its CC0 Wikidata
short description, falling back to the public-domain IAU name-origin blurb —
never the Wikipedia extract, which is CC BY-SA with no credit surface on a card.

`lastmod` is the export date (uniform — the export is when content last
changed). Above 45 k URLs the writer warns; splitting into a sitemap index
would then also need matching chunk routes in the frontend proxy.

## Page records — `seo/pages.json.gz`

One record for each page of the sitemap, keyed by the path of its file in the
site's assets:

- `o/<object id>` — `{global, localized, credits}`;
- `g/<slug>` — `{global, localized, credits}`, where `global.images` holds the
  group's lead image only;
- `f/<body id>/<feature id>` — `{global, localized, credits, names}`.

`global` holds the fields of the page's `__global__` bundle entry that
`meta.ts` reads (its `Seo*` types), or is null when the bundles have no entry.
`localized` holds the same for each language that has an entry. `images` keeps
only the first photo and the first logo of each of the `free` and `credit`
tiers, which leaves the choice of the card image unchanged. `credits` holds the
`license.name` and `artist` of each `credit` image, as its variants embed them,
by file. `names` is the feature's line in each language's label file.

The frontend build writes each record into the site's own static assets
(`frontend/scripts/seo-pages.mjs`, adding the `images` token of
`metadata.json` as `v`). The Worker then reads a file of a few KB where the
bundles are buckets of a few MB: parsing them was most of its CPU time. A page
that has no record reads the bundles, and a record shows the export as it was
when the site was built.
