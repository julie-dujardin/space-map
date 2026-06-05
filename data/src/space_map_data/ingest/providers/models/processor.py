"""ModelProcessor: read 3D manifests, convert + optimise, emit per-slug glTF bundles.

Pipeline:
1. Convert every convertible source file in every manifest entry to a
   compressed (high+low knobs) GLB in ``CONVERTED_DIR`` — caches across runs.
2. Per entry, compare cached candidates' post-compression sizes and pick:
   - high = largest ``.high.glb`` ≤ ``MAX_FILE_BYTES``
   - low  = smallest ``.low.glb`` ≤ ``MAX_FILE_BYTES``
   When no candidate's high fits under the cap, the slug is skipped with a
   warning (don't ship something that won't deploy to Pages).
3. Hardlink the picks into ``EXPORT_DIR/v1/models/{slug}/{high,low}.glb``
   (copy fallback on cross-fs); write slim per-tier prod metadata.json.
4. Write a debug sidecar to ``EXPORT_METADATA_DIR/v1/models/{slug}/`` with
   every candidate's size/sha + the pick reasoning + invalidation key.
5. Point each mission's ``Object.model_name`` at its winning slug.

Slugs are unique across all manifests (NASA + ESA + merged.yaml). Merged
entries win for ``Object.model_name`` since their manifest loads first.
"""

import json
import logging
import os
import shutil
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from ruamel.yaml import YAML
from tqdm import tqdm

from space_map_data.constants.earth_sats.satellite_models import SATELLITE_BUSES
from space_map_data.ingest.providers.models import cache, config, conversion, metadata
from space_map_data.models.object import Object
from space_map_data.models.object.satcat import Satcat
from space_map_data.utils.db import get_session
from space_map_data.utils.paths import EXPORT_METADATA_DIR

log = logging.getLogger(__name__)

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.width = 4096  # don't reflow long URLs/notes

# Only artificial-object kinds get a 3D model. Naturally-occurring bodies
# (asteroid, astronomical_object) render with their real shape/texture, even
# when a manifest entry resolves them to a DB Object via spkid/naif_id.
SPACECRAFT_KINDS = frozenset(
    {
        "earth_sat",
        "probe",
        "lander",
        "generic_sat",
        "station",
        "rocket",
        "robot",
        "submersible",
        "aircraft",
    }
)


class SlugConflictError(RuntimeError):
    """Two manifest entries share the same slug — names must be globally unique."""


def _nasa_checkout_iso() -> str | None:
    """ISO timestamp of the last commit on the NASA-3D-Resources checkout.

    Used as ``downloaded_at`` for NASA models — the repo doesn't ship a
    machine-readable fetch time, but the checkout's HEAD commit time is the
    closest available proxy (it bumps every ``git pull``). Returns None when
    the checkout doesn't exist or git is unavailable.
    """
    checkout = config.NASA_CHECKOUT
    if not (checkout / ".git").is_dir():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), "log", "-1", "--format=%cI", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ):
        return None
    return result.stdout.strip() or None


class ModelProcessor:
    def __init__(self) -> None:
        self._yaml_docs: list[tuple[Path, dict]] = []
        self._catalog_downloaded_at: dict[str, str] = {}
        self._has_blender = conversion.blender_available()
        self._has_gltf_transform = conversion.gltf_transform_available()
        self._nasa_downloaded_at = _nasa_checkout_iso()
        if not self._has_blender:
            log.warning(
                "blender not on PATH — .fbx/.blend/.obj/.3ds models will be skipped. "
                "Install Blender to convert non-glTF sources."
            )
        if not self._has_gltf_transform:
            log.warning(
                "gltf-transform CLI not on PATH — models will be copied verbatim "
                "without Meshopt/WebP compression. `pnpm i -g @gltf-transform/cli` "
                "(or rely on npx) to enable."
            )

    def process_all(self, force: bool = False) -> None:
        self._load_manifests()
        self._check_slug_uniqueness()

        # DB + bus context up-front so the prune pass below sees which slugs
        # actually wire up to a runtime Object. Without this, entries whose
        # missions only carry a `name:` (no probe_id/naif_id/norad/spkid)
        # would leave orphan bundles shipping on the CDN forever.
        self._satcat_norad_to_object_id = self._load_satcat_object_ids()
        self._satcat_name_to_norad = self._load_satcat_name_to_norad()
        # model_slug → bus spec; lets us treat a manifest entry as "wanted"
        # when a SATELLITE_BUS spec depends on it.
        self._buses_by_model_slug: dict[str, list] = defaultdict(list)
        for spec in SATELLITE_BUSES:
            if spec.model_slug:
                self._buses_by_model_slug[spec.model_slug].append(spec)
        db_object_ids = self._load_db_object_ids()

        wanted_slugs = {
            entry["slug"]
            for _yaml_path, doc in self._yaml_docs
            for entry in doc.get("entries") or []
            if entry.get("slug") and self._entry_has_db_mission(entry, db_object_ids)
        }

        self._prune_stale_bundles(wanted_slugs)
        self._prune_stale_caches()
        self._reset_model_pointer()

        # First slug to claim a mission wins; assignment becomes Object.model_name
        # at the end. Future-work TODO: explicit per-mission winner selection
        # when several slugs depict the same mission (e.g. "cassini-with-huygens"
        # vs "cassini").
        mission_winners = self._assign_mission_winners()

        all_entries: list[tuple[Path, dict]] = [
            (yaml_path, entry)
            for yaml_path, doc in self._yaml_docs
            for entry in doc.get("entries") or []
            if self._entry_has_db_mission(entry, db_object_ids)
        ]
        for yaml_path, entry in tqdm(all_entries, desc="3D models", unit="entry"):
            self._process_entry(entry, yaml_path, force=force)

        self._write_mission_pointers(mission_winners)
        self._write_bus_pointers()

    def _load_manifests(self) -> None:
        """Discover every 3D manifest under ``MODELS_DOWNLOAD_DIR``.

        Load order matters for ``_assign_mission_winners`` (first slug per
        mission wins): merged → NASA → ESA. Merged entries pull files from
        multiple catalogs and represent the curated canonical choice, so
        they should win over the equivalent per-catalog entries.
        """
        self._yaml_docs = []
        if config.MERGED_MANIFEST.exists():
            self._yaml_docs.append(
                (config.MERGED_MANIFEST, _yaml.load(config.MERGED_MANIFEST.read_text()))
            )
        if config.NASA_MANIFEST.exists():
            self._yaml_docs.append(
                (config.NASA_MANIFEST, _yaml.load(config.NASA_MANIFEST.read_text()))
            )
        else:
            log.info("no NASA manifest at %s", config.NASA_MANIFEST)
        if config.ESA_DIR.exists():
            for sub in sorted(config.ESA_DIR.iterdir()):
                meta = sub / "metadata.yaml"
                if meta.is_file():
                    self._yaml_docs.append((meta, _yaml.load(meta.read_text())))

        # Cache catalog-name → downloaded_at so merged-manifest entries
        # (which lack a top-level source) can still surface freshness per file.
        self._catalog_downloaded_at = {}
        for _path, doc in self._yaml_docs:
            source = doc.get("source") or {}
            name = source.get("name") or source.get("catalog")
            ts = source.get("downloaded_at")
            if name and ts:
                self._catalog_downloaded_at[name] = ts
        if self._nasa_downloaded_at:
            self._catalog_downloaded_at.setdefault(
                "NASA-3D-Resources", self._nasa_downloaded_at
            )

    def _prune_stale_bundles(self, wanted_slugs: set[str]) -> None:
        """Delete bundle and sidecar dirs whose slug isn't a wanted-shipping target.

        "Wanted" = slug is declared in a manifest **and** its entry resolves
        to at least one DB Object (or bus member). Entries whose missions
        only carry a ``name:`` (no probe_id/naif_id/norad/spkid — e.g.
        ARIEL, SMILE) are no-ops at runtime, so their bundles shouldn't
        ship. Renamed / removed slugs (``aqua-a``/``-b``/``-c`` → ``aqua``)
        also get cleaned up here.
        """
        for root, label in (
            (config.PROCESSED_DIR, "model bundle"),
            (EXPORT_METADATA_DIR / "v1" / "models", "model sidecar"),
        ):
            if not root.exists():
                continue
            pruned = 0
            for slug_dir in root.iterdir():
                if not slug_dir.is_dir() or slug_dir.name.startswith("."):
                    continue
                if slug_dir.name in wanted_slugs:
                    continue
                log.info("pruning stale %s: %s", label, slug_dir.name)
                shutil.rmtree(slug_dir)
                pruned += 1
            if pruned:
                log.info("pruned %d stale %s(s)", pruned, label)

    def _prune_stale_caches(self) -> None:
        """Drop converted-cache subdirs whose slug is no longer in any manifest.

        Per-source orphans (one file removed from an entry that still
        exists) are handled per-entry inside ``_process_entry`` since we
        need the live ``file_id`` set there anyway.
        """
        pruned = cache.prune_slug_dirs(self._manifest_slugs())
        if pruned:
            log.info("pruned %d stale converted-cache slug dir(s)", pruned)

    def _manifest_slugs(self) -> set[str]:
        return {
            entry["slug"]
            for _path, doc in self._yaml_docs
            for entry in (doc.get("entries") or [])
            if entry.get("slug")
        }

    def _check_slug_uniqueness(self) -> None:
        """Hard-fail if two entries (any catalog) share a slug.

        Slugs name the on-disk model dir and are the value the DB's
        ``model_name`` column points at; collisions would silently overwrite
        each other's GLBs.
        """
        seen: dict[str, Path] = {}
        for yaml_path, doc in self._yaml_docs:
            for entry in doc.get("entries") or []:
                slug = entry.get("slug")
                if not slug:
                    continue
                prior = seen.get(slug)
                if prior is not None:
                    raise SlugConflictError(
                        f"slug {slug!r} declared in both {prior} and {yaml_path}"
                    )
                seen[slug] = yaml_path

    def _assign_mission_winners(self) -> dict[str, str]:
        """Build {object_id: slug} for every mission across all manifests.

        Tiebreak when one mission has multiple candidate slugs:
        - entries flagged ``canonical: true`` win over un-flagged peers;
        - among equally-flagged entries, first-encountered wins (load order
          is merged.yaml → NASA → ESA alphabetical).

        A canonical-vs-canonical conflict on the same mission is a config
        error and logs at warning level — both can't be the primary model.
        """
        candidates: dict[str, list[tuple[str, bool]]] = defaultdict(list)
        for _yaml_path, doc in self._yaml_docs:
            for entry in doc.get("entries") or []:
                slug = entry.get("slug")
                if not slug:
                    continue
                kind = entry.get("kind") or entry.get("type")
                if kind not in SPACECRAFT_KINDS:
                    continue
                canonical = bool(entry.get("canonical"))
                for mission in entry.get("missions") or []:
                    oid = metadata.resolve_mission_object_id(
                        mission, self._satcat_norad_to_object_id
                    )
                    if oid is None:
                        continue
                    candidates[oid].append((slug, canonical))

        winners: dict[str, str] = {}
        for oid, entries in candidates.items():
            # `canonical=True` first, then preserve load order — stable sort
            # keys preserve original order within each canonical/non-canonical
            # group, so first-encountered still wins inside each bucket.
            sorted_entries = sorted(entries, key=lambda e: not e[1])
            winners[oid] = sorted_entries[0][0]
            if len(entries) > 1:
                canonical_count = sum(1 for _s, c in entries if c)
                if canonical_count > 1:
                    log.warning(
                        "mission %s has %d entries with canonical=true %s — "
                        "picking %s (load order); fix the manifest",
                        oid,
                        canonical_count,
                        [s for s, c in entries if c],
                        sorted_entries[0][0],
                    )
                else:
                    log.info(
                        "mission %s has multiple model slugs %s — picking %s%s",
                        oid,
                        [s for s, _c in entries],
                        sorted_entries[0][0],
                        " (canonical flag)"
                        if sorted_entries[0][1]
                        else " (first in load order)",
                    )
        return winners

    def _reset_model_pointer(self) -> None:
        session = get_session()
        session.query(Object).update({Object.model_name: None})
        session.commit()

    def _load_db_object_ids(self) -> set[str]:
        session = get_session()
        return {row[0] for row in session.query(Object.id).all()}

    def _load_satcat_object_ids(self) -> dict[int, str]:
        """Map every satcat NORAD → its actual ``Object.id``.

        After CelesTrak ingest, each satcat NORAD is claimed by exactly one
        Object via ``Object.satcat_norad_cat_id`` — either a ``norad_satcat-N``
        stub or, when consolidated via COSPAR, an existing probe Object
        (e.g. NORAD 25008 → ``probe-88592384``). For joint launches that
        produce multiple probe claims sharing a NORAD, we pick the first
        one returned by the query (deterministic in practice via DB row
        order — Phase 5 will tighten this).
        """
        session = get_session()
        out: dict[int, str] = {}
        for norad, oid in (
            session.query(Object.satcat_norad_cat_id, Object.id)
            .where(Object.satcat_norad_cat_id.is_not(None))
            .all()
        ):
            out.setdefault(norad, oid)
        return out

    def _entry_has_db_mission(self, entry: dict, db_object_ids: set[str]) -> bool:
        """Skip entries that resolve to no Object row — saves Blender/gltf work
        on generic catalog assets (tools, ground infra, unbuilt concepts) that
        no mission would ever reference. An entry is also kept when a
        ``SatelliteBusSpec.model_slug`` points at it and at least one of the
        bus's ``known_satellites`` exists in the Object table.

        Also drops naturally-occurring bodies (asteroid, astronomical_object)
        even when they resolve cleanly — those should render with their actual
        shape/texture, not a NASA 3D asset."""
        kind = entry.get("kind") or entry.get("type")
        if kind not in SPACECRAFT_KINDS:
            return False
        slug = entry.get("slug")
        if slug is not None:
            for spec in self._buses_by_model_slug.get(slug, ()):
                if self._bus_object_ids(spec, db_object_ids):
                    return True
        for mission in entry.get("missions") or []:
            oid = metadata.resolve_mission_object_id(
                mission, self._satcat_norad_to_object_id
            )
            if oid is not None and oid in db_object_ids:
                return True
        return False

    def _bus_object_ids(self, spec, db_object_ids: set[str]) -> list[str]:
        """Object IDs for every ``known_satellites`` entry currently in DB."""
        out: list[str] = []
        for name in spec.known_satellites:
            norad = self._satcat_name_to_norad.get(name.strip())
            if norad is None:
                continue
            oid = self._satcat_norad_to_object_id.get(norad)
            if oid is not None and oid in db_object_ids:
                out.append(oid)
        return out

    def _load_satcat_name_to_norad(self) -> dict[str, int]:
        session = get_session()
        return {
            name: norad
            for norad, name in session.query(
                Satcat.NORAD_CAT_ID, Satcat.OBJECT_NAME
            ).all()
            if name
        }

    def _write_bus_pointers(self) -> None:
        """Apply ``SatelliteBusSpec.model_slug`` to every bus satellite.

        Runs after ``_write_mission_pointers`` so explicit per-mission
        manifest assignments win — bus assignments only fill empty slots."""
        session = get_session()
        db_object_ids = {row[0] for row in session.query(Object.id).all()}
        assigned = 0
        for spec in SATELLITE_BUSES:
            if not spec.model_slug:
                continue
            oids = self._bus_object_ids(spec, db_object_ids)
            if not oids:
                continue
            for oid in oids:
                rowcount = (
                    session.query(Object)
                    .filter(Object.id == oid, Object.model_name.is_(None))
                    .update({Object.model_name: spec.model_slug})
                )
                assigned += int(rowcount or 0)
        session.commit()
        if assigned:
            log.info("bus pointers: wrote model_name on %d Objects", assigned)

    def _write_mission_pointers(self, winners: dict[str, str]) -> None:
        """Write the resolved ``model_name`` pointer for every mission winner.

        Missing object_ids (mission resolved but no DB row) are silently
        skipped — the .update() on an empty filter is a no-op. Hand-authored
        manifests like Cluster II's NORAD list often include decayed
        satellites with no DB presence; we don't want to break ingest for
        catalog-authoring drift.
        """
        session = get_session()
        for oid, slug in winners.items():
            session.query(Object).filter(Object.id == oid).update(
                {Object.model_name: slug}
            )
        session.commit()

    def _process_entry(self, entry: dict, yaml_path: Path, *, force: bool) -> None:
        slug = entry.get("slug")
        if not slug:
            log.warning("%s: entry without slug — skipping", yaml_path.name)
            return

        candidates = metadata.convertible_files(entry.get("files") or [])
        if not candidates:
            log.warning(
                "%s: no convertible file in entry (have: %s)",
                slug,
                [m.get("type") for m in entry.get("files") or []],
            )
            return

        # Materialise (cache-or-build) every candidate's compressed pair.
        cached: list[tuple[dict, cache.Cached]] = []
        for f in candidates:
            src_path = config.MODELS_DOWNLOAD_DIR / f["path"]
            if not src_path.exists():
                log.warning("%s: missing source %s", slug, f["path"])
                continue
            try:
                c = cache.ensure_cached(
                    slug=slug,
                    source_path=src_path,
                    source_type=f["type"],
                    has_blender=self._has_blender,
                    has_gltf_transform=self._has_gltf_transform,
                )
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "")[-500:]
                # Per-candidate failure isn't fatal — the picker still picks
                # from whatever else converted.
                log.info("candidate skipped for %s/%s: %s", slug, f["path"], stderr)
                continue
            if c is None:
                continue
            cached.append((f, c))

        # Drop cache files for sources that disappeared from this entry.
        cache.prune_orphan_files(slug, {c.file_id for _f, c in cached})

        if not cached:
            log.warning("%s: no candidate produced a converted GLB", slug)
            return

        # Pick by post-compression size. Filter by Cloudflare cap on high
        # tier; if nothing fits, skip the slug — partial deploys aren't worth
        # the half-rendered bodies in prod.
        eligible = [
            (f, c) for f, c in cached if 0 < c.size("high") <= config.MAX_FILE_BYTES
        ]
        if not eligible:
            sizes = ", ".join(f"{c.file_id}={c.size('high')}B" for _f, c in cached)
            log.warning(
                "%s: skipping — no candidate ≤ %dB after compression (%s)",
                slug,
                config.MAX_FILE_BYTES,
                sizes,
            )
            # Still write a sidecar so debugging the rejection is possible.
            self._write_sidecar_metadata(
                slug=slug,
                entry=entry,
                yaml_path=yaml_path,
                cached=cached,
                high_pick=None,
                low_pick=None,
            )
            # And clear any stale prod bundle (slug used to ship, no longer does).
            _rm_export_bundle(slug)
            return

        # high = largest (best fidelity); low = smallest (fast load).
        # A file may set `preferred: true` to override the size-based high
        # pick (the largest isn't always the best — sometimes it's the most
        # cluttered). When the preferred file's high tier blows the cap,
        # warn and fall back to size-based pick.
        preferred = [(f, c) for f, c in eligible if f.get("preferred")]
        if len(preferred) > 1:
            log.warning(
                "%s: multiple files marked preferred: true %s — using first",
                slug,
                [f["path"] for f, _c in preferred],
            )
        if preferred:
            high_pick = preferred[0]
        else:
            over_cap_preferred = [f for f, _c in cached if f.get("preferred")]
            if over_cap_preferred:
                log.warning(
                    "%s: preferred file(s) %s exceeded cap after compression — "
                    "falling back to size-based pick",
                    slug,
                    over_cap_preferred,
                )
            high_pick = max(eligible, key=lambda fc: fc[1].size("high"))
        low_pick = min(eligible, key=lambda fc: fc[1].size("low"))
        # If the low candidate's `.low.glb` is also over cap, fall back to
        # using its `.high.glb` (gltf-transform missing or it bloated). The
        # picker's cap guarantee only covers the high tier.
        if (
            low_pick[1].size("low") > config.MAX_FILE_BYTES
            or low_pick[1].size("low") == 0
        ):
            low_pick = high_pick  # share with high; .low.glb is what gets hardlinked

        # Resolve catalog metadata up-front so cap_hash sees it: tweaks to
        # _catalog_by_tier (e.g. rewriting non-catalog source → attribution)
        # then invalidate existing sidecars and force a re-emit.
        catalog_by_tier = self._catalog_by_tier(yaml_path, high_pick[0], low_pick[0])
        out_dir = config.PROCESSED_DIR / slug
        cap_hash = self._cap_hash(cached, high_pick, low_pick, catalog_by_tier)
        if not force and self._sidecar_says_unchanged(slug, cap_hash):
            return

        _link_into_export(high_pick[1].high_glb, out_dir / "high.glb")
        low_source = low_pick[1].low_glb or low_pick[1].high_glb
        _link_into_export(low_source, out_dir / "low.glb")

        exports = {
            "high": self._tier_record(
                out_dir / "high.glb", high_pick, catalog_by_tier["high"]
            ),
            "low": self._tier_record(
                out_dir / "low.glb", low_pick, catalog_by_tier["low"]
            ),
        }
        self._write_prod_metadata(
            out_dir=out_dir, slug=slug, entry=entry, exports=exports
        )
        self._write_sidecar_metadata(
            slug=slug,
            entry=entry,
            yaml_path=yaml_path,
            cached=cached,
            high_pick=high_pick,
            low_pick=low_pick,
            catalog_by_tier=catalog_by_tier,
        )
        log.info(
            "processed %s (high=%s, low=%s)",
            slug,
            high_pick[1].file_id,
            low_pick[1].file_id,
        )

    def _cap_hash(
        self,
        cached: list[tuple[dict, cache.Cached]],
        high_pick: tuple[dict, cache.Cached],
        low_pick: tuple[dict, cache.Cached],
        catalog_by_tier: dict[str, dict],
    ) -> dict:
        """Build the invalidation key the next run compares against the sidecar.

        Includes every cached candidate's source-sha — so if a previously
        rejected oversize file is replaced with a smaller version, the
        rerun picks it up. Also includes the picks themselves so a manual
        retune of MAX_FILE_BYTES forces a re-link, and the resolved
        per-tier catalog dict so any change to ``_catalog_by_tier``
        output (source/attribution/url) re-emits the bundle.
        """
        return {
            "schema": config.SCHEMA_VERSION,
            "knobs": config.COMPRESSION_KNOBS_VERSION,
            "max_file_bytes": config.MAX_FILE_BYTES,
            "candidates": sorted(
                {c.file_id: c.source_sha256 for _f, c in cached}.items()
            ),
            "high": high_pick[1].file_id,
            "low": low_pick[1].file_id,
            "catalog": {
                "high": sorted(catalog_by_tier["high"].items()),
                "low": sorted(catalog_by_tier["low"].items()),
            },
        }

    def _sidecar_says_unchanged(self, slug: str, cap_hash: dict) -> bool:
        sidecar_path = _sidecar_path(slug)
        if not sidecar_path.exists():
            return False
        # Must also confirm the public bundle still exists — sidecar could
        # outlive a manually-deleted EXPORT_DIR slug dir.
        if not (config.PROCESSED_DIR / slug / "high.glb").exists():
            return False
        try:
            existing = json.loads(sidecar_path.read_text())
        except (OSError, json.JSONDecodeError):
            return False
        return existing.get("invalidation") == cap_hash

    def _tier_record(
        self,
        glb_path: Path,
        pick: tuple[dict, cache.Cached],
        catalog: dict,
    ) -> dict:
        """Per-tier prod metadata: file stats + per-tier catalog provenance.

        Catalog fields live per-tier (not at the top level) because high
        and low may originate in different catalogs for merged entries.
        """
        f, c = pick
        record: dict = {
            "size_bytes": glb_path.stat().st_size,
            "sha256": metadata.sha256_file(glb_path),
            "source_type": c.source_type,
            **catalog,
        }
        stats = metadata.gltf_stats(glb_path)
        if stats:
            record["stats"] = stats
        return record

    def _catalog_by_tier(
        self,
        yaml_path: Path,
        high_src: dict,
        low_src: dict,
    ) -> dict[str, dict]:
        """Per-tier ``{credit: {name, url}, catalog?, downloaded_at?}``.

        ``credit.name`` is always the attribution (inline or catalog
        default), so the frontend chip says e.g. "NASA" regardless of
        whether the file came from NASA-3D-Resources, a one-off NASA
        Science resource page, or a Google rehost. ``credit.url`` prefers
        the inline ``source_url`` (specific resource page) and falls back
        to the catalog landing page. ``catalog`` is only emitted when
        the file's source matches a key in ``MODEL_CATALOGS`` — the
        credits.json roll-up uses it to pick primary catalog credits.
        """
        doc = next((d for p, d in self._yaml_docs if p == yaml_path), None) or {}
        doc_source = doc.get("source") or {}
        doc_name = doc_source.get("name") or doc_source.get("catalog")

        def resolve(f: dict) -> dict:
            name = f.get("source") or doc_name
            if not name:
                log.warning(
                    "file %r has no source and parent manifest %s has no top-level source",
                    f.get("path"),
                    yaml_path.name,
                )
                return {}
            catalog = config.MODEL_CATALOGS.get(name)
            inline_url = f.get("source_url")
            inline_attribution = f.get("attribution")
            if inline_attribution:
                credit_name = inline_attribution
            elif catalog:
                # Per-manifest attribution overrides the catalog default.
                manifest_attribution = (
                    doc_source.get("attribution") if name == doc_name else None
                )
                credit_name = (
                    manifest_attribution
                    if isinstance(manifest_attribution, str)
                    else catalog["default_attribution"]
                )
            else:
                log.warning(
                    "file %r: source %r not in MODEL_CATALOGS and missing inline attribution",
                    f.get("path"),
                    name,
                )
                return {}
            credit_url = inline_url or (catalog["url"] if catalog else None)
            out: dict = {"credit": {"name": credit_name, "url": credit_url}}
            if catalog:
                out["catalog"] = name
            ts = self._catalog_downloaded_at.get(name)
            if ts:
                out["downloaded_at"] = ts
            return out

        return {"high": resolve(high_src), "low": resolve(low_src)}

    def _missions_block(self, entry: dict) -> list[dict]:
        """Convert ``missions:`` to ``[{object_id, name?}, …]``, dropping unresolvable."""
        out: list[dict] = []
        for mission in entry.get("missions") or []:
            oid = metadata.resolve_mission_object_id(
                mission, self._satcat_norad_to_object_id
            )
            if oid is None:
                continue
            item: dict = {"object_id": oid}
            if mission.get("name"):
                item["name"] = mission["name"]
            out.append(item)
        return out

    def _write_prod_metadata(
        self,
        *,
        out_dir: Path,
        slug: str,
        entry: dict,
        exports: dict[str, dict],
    ) -> None:
        """Write the public ``EXPORT_DIR/v1/models/{slug}/metadata.json``.

        Slim: slug + schema + kind + missions + per-tier exports. No
        invalidation keys or candidate lists — those live in the sidecar so
        the CDN page doesn't ship debug noise.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        payload: dict = {
            "slug": slug,
            "schema": config.SCHEMA_VERSION,
            "kind": entry.get("kind") or entry.get("type"),
            "missions": self._missions_block(entry),
            "tiers": sorted(exports.keys()),
            "exports": exports,
            "processed_at": datetime.now(UTC).isoformat(),
        }
        (out_dir / "metadata.json").write_text(json.dumps(payload, indent=2))

    def _write_sidecar_metadata(
        self,
        *,
        slug: str,
        entry: dict,
        yaml_path: Path,
        cached: list[tuple[dict, cache.Cached]],
        high_pick: tuple[dict, cache.Cached] | None,
        low_pick: tuple[dict, cache.Cached] | None,
        catalog_by_tier: dict[str, dict] | None = None,
    ) -> None:
        """Write the build-side debug sidecar under ``EXPORT_METADATA_DIR``.

        Carries every candidate's converted size/sha + rejection reason +
        the invalidation key. Doubles as the ``_try_skip`` substitute on
        the next run so we don't have to inspect the prod metadata.
        """
        sidecar_path = _sidecar_path(slug)
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)

        candidates: list[dict] = []
        for f, c in cached:
            high_sz = c.size("high")
            low_sz = c.size("low")
            rejection = None
            if high_sz == 0:
                rejection = "high conversion missing"
            elif high_sz > config.MAX_FILE_BYTES:
                rejection = f"high size {high_sz} > cap {config.MAX_FILE_BYTES}"
            candidates.append(
                {
                    "source_path": f["path"],
                    "source_catalog": f.get("source"),  # merged-manifest only
                    "source_type": c.source_type,
                    "source_sha256": c.source_sha256,
                    "file_id": c.file_id,
                    "high_size": high_sz,
                    "low_size": low_sz,
                    "rejected": rejection,
                }
            )

        picks = None
        if high_pick is not None and low_pick is not None:
            picks = {"high": high_pick[1].file_id, "low": low_pick[1].file_id}

        payload: dict = {
            "slug": slug,
            "schema": config.SCHEMA_VERSION,
            "manifest": str(yaml_path.relative_to(config.MODELS_DOWNLOAD_DIR)),
            "candidates": candidates,
            "picks": picks,
            "invalidation": (
                self._cap_hash(cached, high_pick, low_pick, catalog_by_tier or {})
                if high_pick is not None
                and low_pick is not None
                and catalog_by_tier is not None
                else None
            ),
            "processed_at": datetime.now(UTC).isoformat(),
        }
        sidecar_path.write_text(json.dumps(payload, indent=2))


def _sidecar_path(slug: str) -> Path:
    return EXPORT_METADATA_DIR / "v1" / "models" / slug / "metadata.json"


def _link_into_export(src: Path, dst: Path) -> None:
    """Hardlink ``src`` → ``dst``; fall back to copy on cross-fs (EXDEV)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError as exc:
        if exc.errno not in (18,):  # EXDEV = cross-device link not permitted
            raise
        shutil.copyfile(src, dst)


def _rm_export_bundle(slug: str) -> None:
    """Remove a prod bundle dir if it exists (skipped slugs shouldn't ship)."""
    bundle = config.PROCESSED_DIR / slug
    if bundle.exists():
        shutil.rmtree(bundle)
