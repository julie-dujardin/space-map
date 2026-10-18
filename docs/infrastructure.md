# Infrastructure

```mermaid
flowchart LR
  user((User browser))
  sources((Data sources<br/>CelesTrak, Space-Track, JPL,<br/>Wikidata, cloud maps, ...))
  feeds((DSN Now - ESTRACK Now<br/>DSN bot on Bluesky))

  subgraph repo["GitHub: space-map"]
    direction TB
    src_fe[frontend/]
    src_data[data/]
    src_sched[infrastructure/scheduler/]
    src_tiles[infrastructure/tiles/]
    src_search[infrastructure/search/]
    src_live[infrastructure/live/]
  end

  subgraph ci["GitHub Actions"]
    direction TB
    wf_fe[frontend-deploy]
    wf_data[data-deploy]
  end

  ghcr[("ghcr.io/.../space-map-data")]
  ghrel[("GitHub Releases")]

  subgraph cf["Cloudflare"]
    direction TB
    live[("Workers static assets<br/>live.spacemap.co<br/>(v1/activity.json)")]
    searchhost["search.spacemap.co"]
    worker["Worker space-map<br/>spacemap.co<br/>(pages, /api/search-key)"]
    edge["Edge cache<br/>tiles.spacemap.co"]
    static[("Workers static assets<br/>static.spacemap.co: data<br/>images.spacemap.co: v1/images")]
  end

  subgraph lan["Home LAN"]
    direction TB
    workstation["Workstation<br/>ingest, export, deploy.sh<br/>(by hand)"]
    subgraph eu0["eu-0: homelab, Debian VM"]
      direction TB
      portainer[Portainer]
      tilescaddy["tiles stack: Caddy<br/>(:9752, read-only file server)"]
      scheduler["space-map-data<br/>(scheduled downloads)"]
      grafana["Loki / Prometheus / Grafana<br/>(stdout and metrics)"]
    end
    nas[("NAS<br/>space-map-downloads<br/>space-map-tiles")]
  end

  subgraph eu1["eu-1: OVH VPS"]
    direction TB
    sg["spaceguesser multiplayer<br/>(other repo)"]
    subgraph search["search stack"]
      direction TB
      caddy["Caddy<br/>(search-only proxy, no host port)"]
      meili["Meilisearch<br/>(:9751 on loopback, master key)"]
    end
    livestack["live stack<br/>(tracking poller, deploy on change)"]
  end

  src_fe --> wf_fe
  src_data --> wf_data
  src_sched --> wf_data
  wf_fe -->|"wrangler deploy"| worker
  wf_data -->|"docker push :version :sha :latest"| ghcr
  wf_data --> ghrel

  src_sched -.->|deploy| portainer
  src_tiles -.->|deploy| portainer
  src_search -.->|deploy| search
  src_live -.->|deploy| livestack
  ghcr -.->|pull| portainer
  ghcr -.->|pull| livestack
  portainer --> scheduler
  portainer --> tilescaddy

  scheduler -.->|regular fetch| sources
  scheduler -->|NFS| nas
  tilescaddy -->|"NFS, read-only"| nas
  workstation -->|NFS| nas
  workstation -->|"wrangler deploy"| static
  workstation -->|"ssh -L 9751<br/>space-map-search push"| meili

  livestack -.->|every minute| feeds
  livestack -->|"wrangler deploy"| live
  meili ~~~ sg
  tilescaddy ~~~ scheduler

  user -->|"pages, and a Turnstile proof<br/>for a one-hour search key"| worker
  user --> static
  user --> live
  user -->|"search (using that key)"| searchhost
  searchhost -->|"search stack's own tunnel"| caddy
  caddy --> meili
  user -->|"surface tiles"| edge
  edge -->|"homelab tunnel, :9752<br/>tiles the edge does not hold"| tilescaddy
```

## EU-0

The homelab server. See [julie-dujardin/homelab](https://github.com/julie-dujardin/homelab)
for sources. It mounts the NAS, which holds the downloads and the tile tree.
The export and its deploy are not scheduled yet: they run by hand from the
workstation.

## EU-1

The OVH VPS. It has its own disk and no access to the NAS or the LAN, so data
that it needs goes over by rsync. It also runs the multiplayer server of
[spaceguesser](https://github.com/julie-dujardin/spaceguesser).
