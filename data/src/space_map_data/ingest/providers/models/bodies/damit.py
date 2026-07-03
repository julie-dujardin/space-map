"""DAMIT lightcurve-tier ingest: convex models → GLB bundles + spin orientation.

Reads the extracted DAMIT bulk archive (``DAMIT_DIR``): per-model files under
``files/asteroid_<aid>/model_<mid>/`` plus the CSV tables (``asteroids``,
``asteroid_models`` — spin parameters inline — and the references join table).
Every model is exported (the file cap is 100k; the full set fits); the
preferred model per asteroid drives ``Object.model_name`` and the spin
orientation the frontend applies. Convex models are dimensionless — scaled to
DAMIT's own calibrated diameter when present, else SBDB's measured diameter,
else a diameter estimated from absolute magnitude H — and Blender-free (see
``glb_writer``) so the ~16k-model pass is subprocess-free.

Resumable: a per-model cache stamp (kept outside the export tree — the CDN
has a 100k-file cap) skips already-converted GLBs across runs. No-ops with a
log line when the archive or tables are absent (dev without the 1.4 GB
download).
"""

import csv
import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import numpy as np

from space_map_data.ingest.providers.models import config, metadata
from space_map_data.ingest.providers.models.bodies import glb_writer, orientation
from space_map_data.models.object import ModelProvenance, Object
from space_map_data.utils.paths import DERIVED_MODELS_DIR

log = logging.getLogger(__name__)

# Where the export merges DAMIT-derived spin into the PCK orientation set
# (see export/systems.load_orientation). Keyed by canonical naif_id.
DAMIT_ORIENTATION_CSV = DERIVED_MODELS_DIR / "damit_orientation.csv"
_STAMPS_DIR = DERIVED_MODELS_DIR / "damit_stamps"
_ORIENTATION_FIELDS = [
    "naif_id",
    "pole_ra_0",
    "pole_ra_1",
    "pole_dec_0",
    "pole_dec_1",
    "w0",
    "w1",
    "w2",
]


_J2000_JD = 2451545.0

# H→diameter fallback (Pravec & Harris 2007): D = 1329/√p_V · 10^(−H/5), with
# the CNEOS-assumed albedo when unmeasured. Mirrored in the frontend
# ($lib/math/h-magnitude.ts) so the sidebar estimate matches the model scale.
_H_MAG_CONST_KM = 1329.0
_ASSUMED_ALBEDO = 0.14


@dataclass(frozen=True)
class DamitModel:
    model_id: int
    asteroid_id: int
    lambda_deg: float
    beta_deg: float
    period_h: float
    jd0: float
    phi0_deg: float
    equiv_diameter_km: float | None

    @property
    def dir(self) -> Path:
        return (
            config.DAMIT_DIR
            / "files"
            / f"asteroid_{self.asteroid_id}"
            / f"model_{self.model_id}"
        )


class DamitProcessor:
    """Convert + export the DAMIT convex lightcurve models."""

    def __init__(self, session) -> None:
        self._session = session
        self._orientation_rows: dict[int, dict] = {}

    def available(self) -> bool:
        return config.DAMIT_DIR.exists() and self._tables_dir() is not None

    def wanted_slugs(self) -> set[str]:
        """Slugs for every model that resolves to a DB Object (for pruning)."""
        if not self.available():
            return set()
        models = self._load_models()
        asteroids = self._load_asteroids()
        out: set[str] = set()
        for m in models:
            if self._resolve_object_id(m.asteroid_id, asteroids) is not None:
                out.add(_slug(m.model_id))
        return out

    def process(self, *, force: bool) -> None:
        if not self.available():
            log.info(
                "DAMIT archive/tables absent (%s) — skipping lightcurve tier",
                config.DAMIT_DIR,
            )
            return
        models = self._load_models()
        asteroids = self._load_asteroids()
        citations = self._load_citations()
        diameters = self._load_diameters()

        # Preferred model per asteroid = highest DAMIT model id (newest solution).
        # Drives Object.model_name + the exported spin; all models still ship.
        preferred: dict[int, int] = {}
        for m in models:
            if m.model_id > preferred.get(m.asteroid_id, -1):
                preferred[m.asteroid_id] = m.model_id
        log.info(
            "DAMIT preferred-model policy: newest (max model id) per asteroid; "
            "%d asteroids, %d models",
            len(preferred),
            len(models),
        )

        exported = 0
        for m in models:
            object_id = self._resolve_object_id(m.asteroid_id, asteroids)
            if object_id is None:
                continue
            naif_id = self._naif_for(m.asteroid_id, asteroids)
            if m.equiv_diameter_km is not None:
                diameter, scale_source = m.equiv_diameter_km, "damit"
            elif object_id in diameters:
                diameter, scale_source = diameters[object_id]
            else:
                log.info(
                    "DAMIT model %d (%s): no diameter and no H magnitude — skipping",
                    m.model_id,
                    object_id,
                )
                continue
            is_preferred = preferred.get(m.asteroid_id) == m.model_id
            try:
                ok = self._process_model(
                    m,
                    object_id=object_id,
                    naif_id=naif_id,
                    diameter_km=diameter,
                    scale_source=scale_source,
                    citation=citations.get(m.model_id),
                    is_preferred=is_preferred,
                    force=force,
                )
            except Exception:
                log.exception("DAMIT model %d: conversion failed", m.model_id)
                continue
            if ok:
                exported += 1
                if is_preferred:
                    # Mission/radar bundles (BodyModelProcessor, runs first)
                    # outrank convex lightcurve models — never overwrite them.
                    self._session.query(Object).filter(
                        Object.id == object_id,
                        Object.model_name.is_(None) | Object.model_name.like("damit-%"),
                    ).update(
                        {
                            Object.model_name: _slug(m.model_id),
                            Object.model_provenance: ModelProvenance.lightcurve,
                        },
                        synchronize_session=False,
                    )
        self._write_orientation_csv()
        log.info("DAMIT: exported %d model bundles", exported)

    # --- per-model ---------------------------------------------------------

    def _process_model(
        self,
        m: DamitModel,
        *,
        object_id: str,
        naif_id: int | None,
        diameter_km: float,
        scale_source: str,
        citation: str | None,
        is_preferred: bool,
        force: bool,
    ) -> bool:
        slug = _slug(m.model_id)
        out_dir = config.PROCESSED_DIR / slug
        shape_path = m.dir / "shape.txt"
        if not shape_path.exists():
            log.info("DAMIT model %d: %s not found — skipping", m.model_id, shape_path)
            return False

        # Stamp lives outside the export tree: every exported file counts
        # against the CDN's 100k-file cap.
        stamp = _STAMPS_DIR / f"{slug}.json"
        if force or not _stamp_matches(stamp, out_dir, shape_path, diameter_km):
            verts, faces = _parse_shape(shape_path)
            verts = _scale_to_diameter(verts, faces, diameter_km)
            verts = _body_z_up_to_gltf_y_up(verts)
            # Convex models are already tiny; ship a single "high" tier
            # (a duplicate low.glb would double the exported file count).
            glb_writer.write_glb(verts, faces, out_dir / "high.glb")
            self._write_metadata(
                out_dir,
                slug,
                m,
                object_id,
                naif_id,
                scale_source,
                citation,
                verts,
                faces,
            )
            _write_stamp(stamp, shape_path, diameter_km)

        if is_preferred and naif_id is not None:
            self._orientation_rows[naif_id] = {
                "naif_id": naif_id,
                **self._iau_orientation(m),
            }
        return True

    @staticmethod
    def _iau_orientation(m: DamitModel) -> dict:
        """DAMIT's own IAUspin (α δ Ẇ / epoch W₀) when present, else convert."""
        iau = m.dir / "IAUspin"
        if iau.exists():
            try:
                ra, dec, rate, epoch, w0 = (
                    float(x) for x in iau.read_text().split()[:5]
                )
            except ValueError:
                log.warning("DAMIT model %d: unparseable IAUspin", m.model_id)
            else:
                return {
                    "pole_ra_0": ra,
                    "pole_ra_1": 0.0,
                    "pole_dec_0": dec,
                    "pole_dec_1": 0.0,
                    "w0": (w0 + rate * (_J2000_JD - epoch)) % 360.0,
                    "w1": rate,
                    "w2": 0.0,
                }
        return orientation.damit_to_iau(
            m.lambda_deg, m.beta_deg, m.period_h, m.phi0_deg, m.jd0
        )

    def _write_metadata(
        self,
        out_dir: Path,
        slug: str,
        m: DamitModel,
        object_id: str,
        naif_id: int | None,
        scale_source: str,
        citation: str | None,
        verts: np.ndarray,
        faces: np.ndarray,
    ) -> None:
        permalink = (
            f"https://damit.cuni.cz/projects/damit/asteroids/view/{m.asteroid_id}"
        )
        catalog = "DAMIT"
        credit = {
            "name": config.MODEL_CATALOGS[catalog]["default_attribution"],
            "url": permalink,
        }
        extent = (verts.max(axis=0) - verts.min(axis=0)).tolist()
        half = [e / 2 for e in extent]
        record_stats = {"triangles": len(faces), "meshes": 1, "nodes": 1}
        tier = {
            "size_bytes": (out_dir / "high.glb").stat().st_size,
            "sha256": metadata.sha256_file(out_dir / "high.glb"),
            "source_type": "damit-convex",
            "credit": credit,
            "catalog": catalog,
            "stats": record_stats,
        }
        payload = {
            "slug": slug,
            "schema": config.SCHEMA_VERSION,
            "kind": "shape_model",
            "provenance": "lightcurve",
            "object_id": object_id,
            "naif_id": naif_id,
            "credit": credit,
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "citation": citation,
            "archive": "DAMIT (Database of Asteroid Models from Inversion Techniques)",
            "archive_url": permalink,
            "damit_model_id": m.model_id,
            "damit_asteroid_id": m.asteroid_id,
            "tiers": ["high"],
            "exports": {"high": tier},
            "scale_source": scale_source,
            "true_scale": {
                "max_extent_km": max(extent),
                "bounding_radius_km": float(np.linalg.norm(half)),
                "bbox_min_km": verts.min(axis=0).tolist(),
                "bbox_max_km": verts.max(axis=0).tolist(),
            },
            "processed_at": datetime.now(UTC).isoformat(),
        }
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "metadata.json").write_text(json.dumps(payload, indent=2))

    # --- table + file loading ---------------------------------------------

    def _tables_dir(self) -> Path | None:
        for cand in (config.DAMIT_DIR / "tables", config.DAMIT_DIR):
            if (cand / "asteroid_models.csv").exists() and (
                cand / "asteroids.csv"
            ).exists():
                return cand
        return None

    def _load_models(self) -> list[DamitModel]:
        path = self._tables_dir()
        if path is None:
            return []
        out: list[DamitModel] = []
        for row in _read_csv(path / "asteroid_models.csv"):
            mid = _int(row.get("id"))
            aid = _int(row.get("asteroid_id"))
            spin = [
                _float(row.get(k)) for k in ("lambda", "beta", "period", "jd0", "phi0")
            ]
            if mid is None or aid is None or any(v is None for v in spin):
                log.warning("DAMIT asteroid_models row incomplete — skipping: %s", row)
                continue
            out.append(
                DamitModel(
                    mid,
                    aid,
                    *cast("list[float]", spin),
                    equiv_diameter_km=_float(row.get("equiv_diameter")),
                )
            )
        return out

    def _load_asteroids(self) -> dict[int, dict]:
        path = self._tables_dir()
        if path is None:
            return {}
        out: dict[int, dict] = {}
        for row in _read_csv(path / "asteroids.csv"):
            aid = _int(row.get("id"))
            if aid is None:
                continue
            out[aid] = row
        return out

    def _load_citations(self) -> dict[int, str]:
        """model_id → formatted citation(s), via the references join table."""
        path = self._tables_dir()
        if path is None:
            return {}
        texts: dict[int, str] = {}
        for row in _read_csv(path / "references.csv"):
            rid = _int(row.get("id"))
            if rid is None:
                continue
            parts = [
                row.get("author_short") or row.get("author"),
                f"({row['year']})" if row.get("year") else None,
                row.get("title"),
                row.get("journal"),
            ]
            text = " ".join(p.strip() for p in parts if p and p.strip())
            if text:
                texts[rid] = text
        out: dict[int, str] = {}
        for row in _read_csv(path / "asteroid_models_references.csv"):
            mid = _int(row.get("asteroid_model_id"))
            rid = _int(row.get("reference_id"))
            if mid is None or rid is None or rid not in texts:
                continue
            out[mid] = f"{out[mid]}; {texts[rid]}" if mid in out else texts[rid]
        return out

    def _load_diameters(self) -> dict[str, tuple[float, str]]:
        """(diameter km, scale_source) per object id: measured SBDB diameter
        when present, else the H-magnitude estimate."""
        from space_map_data.models.object.sbdb import SBDB

        out: dict[str, tuple[float, str]] = {}
        for oid, diam, h, albedo in (
            self._session.query(Object.id, SBDB.diameter, SBDB.H, SBDB.albedo)
            .join(SBDB, SBDB.object_id == Object.id)
            .where(SBDB.diameter.is_not(None) | SBDB.H.is_not(None))
        ):
            if diam is not None:
                out[oid] = (float(diam), "sbdb")
            else:
                p_v = float(albedo) if albedo else _ASSUMED_ALBEDO
                d = _H_MAG_CONST_KM / math.sqrt(p_v) * 10 ** (-float(h) / 5.0)
                out[oid] = (d, "h-magnitude")
        return out

    def _resolve_object_id(
        self, asteroid_id: int, asteroids: dict[int, dict]
    ) -> str | None:
        naif = self._naif_for(asteroid_id, asteroids)
        if naif is None:
            return None
        row = self._session.query(Object.id).where(Object.naif_id == naif).first()
        return row[0] if row else None

    @staticmethod
    def _naif_for(asteroid_id: int, asteroids: dict[int, dict]) -> int | None:
        """Canonical naif (2_000_000 + number) from the asteroid's catalog number."""
        row = asteroids.get(asteroid_id)
        if row is None:
            return None
        number = _int(row.get("number") or row.get("astnumber"))
        if number is None:
            return None
        return 2_000_000 + number

    def _write_orientation_csv(self) -> None:
        if not self._orientation_rows:
            return
        DAMIT_ORIENTATION_CSV.parent.mkdir(parents=True, exist_ok=True)
        with DAMIT_ORIENTATION_CSV.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_ORIENTATION_FIELDS)
            writer.writeheader()
            for row in sorted(
                self._orientation_rows.values(), key=lambda r: r["naif_id"]
            ):
                writer.writerow(row)
        log.info(
            "DAMIT: wrote %d spin-orientation rows → %s",
            len(self._orientation_rows),
            DAMIT_ORIENTATION_CSV,
        )


def _slug(model_id: int) -> str:
    return f"damit-{model_id}"


def _parse_shape(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Parse a DAMIT counts-header shape.txt → (verts, 0-based faces)."""
    tokens = path.read_text().split()
    nv, nf = int(tokens[0]), int(tokens[1])
    body = tokens[2:]
    verts = np.array(body[: nv * 3], dtype=np.float64).reshape(nv, 3)
    face_vals = np.array(body[nv * 3 : nv * 3 + nf * 3], dtype=np.int64).reshape(nf, 3)
    return verts, face_vals - 1  # DAMIT faces are 1-based


def _scale_to_diameter(
    verts: np.ndarray, faces: np.ndarray, diameter_km: float
) -> np.ndarray:
    """Scale a dimensionless convex mesh so its volume-equivalent diameter = SBDB.

    Lightcurve inversion fixes shape, not size; SBDB's equivalent-sphere
    diameter is the absolute scale. Recentre on the centroid first.
    """
    verts = verts - verts.mean(axis=0)
    vol = _mesh_volume(verts, faces)
    if vol <= 0:
        return verts  # degenerate; leave as-is (bounds still recorded)
    r_eq = (3.0 * vol / (4.0 * np.pi)) ** (1.0 / 3.0)
    return verts * ((diameter_km / 2.0) / r_eq)


def _body_z_up_to_gltf_y_up(verts: np.ndarray) -> np.ndarray:
    """Rotate body-fixed (pole = +z) vertices into glTF's y-up frame.

    The frontend applies the same IAU quaternion (local +y = pole) to spheres
    and models; the Blender path bakes this rotation via ``export_yup``, so
    the direct writer must match or DAMIT models spin about their side.
    """
    return np.column_stack((verts[:, 0], verts[:, 2], -verts[:, 1]))


def _mesh_volume(verts: np.ndarray, faces: np.ndarray) -> float:
    """Signed volume via the divergence (tetrahedron-sum) method; abs for scale."""
    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    return float(abs(np.sum(np.einsum("ij,ij->i", v0, np.cross(v1, v2))) / 6.0))


def _stamp_matches(stamp: Path, out_dir: Path, shape: Path, diameter_km: float) -> bool:
    if not stamp.exists() or not (out_dir / "high.glb").exists():
        return False
    try:
        data = json.loads(stamp.read_text())
    except OSError, json.JSONDecodeError:
        return False
    return (
        data.get("knobs") == config.DAMIT_KNOBS_VERSION
        and data.get("shape_sha") == metadata.sha256_file(shape)
        and data.get("diameter_km") == diameter_km
    )


def _write_stamp(stamp: Path, shape: Path, diameter_km: float) -> None:
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(
        json.dumps(
            {
                "knobs": config.DAMIT_KNOBS_VERSION,
                "shape_sha": metadata.sha256_file(shape),
                "diameter_km": diameter_km,
            }
        )
    )


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        log.warning("DAMIT table missing: %s", path)
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _int(value) -> int | None:
    try:
        return int(str(value).strip())
    except TypeError, ValueError:
        return None


def _float(value) -> float | None:
    try:
        return float(str(value).strip())
    except TypeError, ValueError:
        return None
