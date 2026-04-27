# Infrastructure

```mermaid
flowchart LR
  user((User browser))
  celestrak((CelesTrak))

  subgraph repo["GitHub: julie-dujardin/space-map"]
    direction TB
    src_fe[frontend/]
    src_data[data/]
    src_infra[infrastructure/data/]
  end

  subgraph ci["GitHub Actions"]
    direction TB
    wf_fe[frontend-deploy]
    wf_data[data-deploy]
  end

  subgraph hosts["Public artifact hosts"]
    direction TB
    cfpagesfront[("Cloudflare Pages - space-map")]
    cfpagesstatic[("Cloudflare Pages - space-map-static")]
    ghcr[("ghcr.io/.../space-map-data")]
    ghrel[("GitHub Releases")]
  end

  subgraph vm["Debian VM"]
    direction TB
    portainer[Portainer]
    container["space-map-data container<br/>(daily scheduler)"]
    grafana[Grafana]
  end

  src_fe --> wf_fe
  src_data --> wf_data
  src_infra --> wf_data

  wf_fe -->|"wrangler pages deploy"| cfpagesfront
  wf_data -->|"docker push :version :sha :latest"| ghcr
  wf_data --> ghrel

  ghcr -.->|pull| portainer
  portainer --> container

  container -->|stdout| grafana
  container -->|"HTTPS daily 12:00 UTC"| celestrak
  container -.->|TODO| cfpagesstatic

  user --> cfpagesfront
  user --> cfpagesstatic
```

- Image tags: `latest`, the version from [`data/pyproject.toml`](../data/pyproject.toml), and the full commit SHA. A matching `vX.Y.Z` GitHub Release is created on first appearance of each version.
