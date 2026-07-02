"""DAMIT lightcurve-tier ingest: convex models → GLB bundles + spin orientation.

Reads the extracted DAMIT bulk archive (``DAMIT_DIR``) plus its CSV table
exports (asteroids / models / references), not a hand-written manifest. Every
model is exported (the file cap is 100k; the full set fits); the preferred
model per asteroid drives ``Object.model_name`` and the spin orientation the
frontend applies. Convex models are dimensionless — scaled to the body's SBDB
diameter — and Blender-free (see ``glb_writer``) so the ~16k-model pass is
subprocess-free.

Resumable: a per-model cache stamp skips already-converted GLBs across runs.
No-ops with a log line when the archive or tables are absent (dev without the
1.4 GB download).
"""

import csv
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from space_map_data.ingest.providers.models import config, metadata
from space_map_data.ingest.providers.models.bodies import glb_writer, orientation
from space_map_data.ingest.providers.models.processor import _link_into_export
from space_map_data.models.object import Object
from space_map_data.utils.paths import DERIVED_MODELS_DIR

log = logging.getLogger(__name__)

# Where the export merges DAMIT-derived spin into the PCK orientation set
# (see export/systems.load_orientation). Keyed by canonical naif_id.
DAMIT_ORIENTATION_CSV = DERIVED_MODELS_DIR / "damit_orientation.csv"
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


@dataclass(frozen=True)
class DamitModel:
    model_id: int
    asteroid_id: int
    reference_id: int | None


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
        references = self._load_references()
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
            diameter = diameters.get(object_id)
            if diameter is None:
                log.info(
                    "DAMIT model %d (%s): no SBDB diameter — skipping",
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
                    references=references,
                    is_preferred=is_preferred,
                    force=force,
                )
            except Exception:
                log.exception("DAMIT model %d: conversion failed", m.model_id)
                continue
            if ok:
                exported += 1
                if is_preferred:
                    self._session.query(Object).filter(Object.id == object_id).update(
                        {Object.model_name: _slug(m.model_id)}
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
        references: dict[int, str],
        is_preferred: bool,
        force: bool,
    ) -> bool:
        slug = _slug(m.model_id)
        out_dir = config.PROCESSED_DIR / slug
        shape_path, spin_path = self._model_files(m.model_id)
        if shape_path is None or spin_path is None:
            log.info("DAMIT model %d: shape/spin file not found — skipping", m.model_id)
            return False

        verts, faces = _parse_shape(shape_path)
        verts = _scale_to_diameter(verts, faces, diameter_km)

        stamp = out_dir / ".damit-cache.json"
        if not force and _stamp_matches(stamp, shape_path, spin_path, diameter_km):
            spin = _parse_spin(spin_path)
        else:
            glb_writer.write_glb(verts, faces, out_dir / "high.glb")
            # Convex models are already tiny; low = high (no LOD tier needed).
            _link_into_export(out_dir / "high.glb", out_dir / "low.glb")
            spin = _parse_spin(spin_path)
            self._write_metadata(
                out_dir, slug, m, object_id, naif_id, references, verts, faces
            )
            _write_stamp(stamp, shape_path, spin_path, diameter_km)

        if is_preferred and naif_id is not None:
            self._orientation_rows[naif_id] = {
                "naif_id": naif_id,
                **orientation.damit_to_iau(
                    spin["lambda"],
                    spin["beta"],
                    spin["period"],
                    spin["phi0"],
                    spin["jd0"],
                ),
            }
        return True

    def _write_metadata(
        self,
        out_dir: Path,
        slug: str,
        m: DamitModel,
        object_id: str,
        naif_id: int | None,
        references: dict[int, str],
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
            "citation": references.get(m.reference_id) if m.reference_id else None,
            "archive": "DAMIT (Database of Asteroid Models from Inversion Techniques)",
            "archive_url": permalink,
            "damit_model_id": m.model_id,
            "damit_asteroid_id": m.asteroid_id,
            "tiers": ["high", "low"],
            "exports": {"high": tier, "low": tier},
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
        """Locate the dir holding asteroids/models CSVs (archive root or /tables)."""
        for cand in (
            config.DAMIT_DIR,
            config.DAMIT_DIR / "tables",
            config.DAMIT_DIR / "exports",
        ):
            if (cand / "models.csv").exists() and (cand / "asteroids.csv").exists():
                return cand
        return None

    def _load_models(self) -> list[DamitModel]:
        path = self._tables_dir()
        if path is None:
            return []
        out: list[DamitModel] = []
        for row in _read_csv(path / "models.csv"):
            mid = _int(row.get("id") or row.get("model_id"))
            aid = _int(row.get("asteroid_id") or row.get("asteroid"))
            if mid is None or aid is None:
                continue
            out.append(
                DamitModel(
                    mid, aid, _int(row.get("reference_id") or row.get("reference"))
                )
            )
        return out

    def _load_asteroids(self) -> dict[int, dict]:
        path = self._tables_dir()
        if path is None:
            return {}
        out: dict[int, dict] = {}
        for row in _read_csv(path / "asteroids.csv"):
            aid = _int(row.get("id") or row.get("asteroid_id"))
            if aid is None:
                continue
            out[aid] = row
        return out

    def _load_references(self) -> dict[int, str]:
        path = self._tables_dir()
        if path is None:
            return {}
        out: dict[int, str] = {}
        for row in _read_csv(path / "references.csv"):
            rid = _int(row.get("id") or row.get("reference_id"))
            if rid is None:
                continue
            text = row.get("reference") or row.get("citation") or row.get("bibcode")
            if text:
                out[rid] = text.strip()
        return out

    def _load_diameters(self) -> dict[str, float]:
        """SBDB equivalent-sphere diameter (km) per object id, for scaling."""
        from space_map_data.models.object.sbdb import SBDB

        out: dict[str, float] = {}
        for oid, diam in (
            self._session.query(Object.id, SBDB.diameter)
            .join(SBDB, SBDB.object_id == Object.id)
            .where(SBDB.diameter.is_not(None))
        ):
            out[oid] = float(diam)
        return out

    def _model_files(self, model_id: int) -> tuple[Path | None, Path | None]:
        """Find a model's shape + spin files under the extracted archive.

        DAMIT's bulk layout isn't documented here; try the common per-model
        patterns and glob as a fallback so a layout change logs-and-skips
        rather than crashing.
        """
        root = config.DAMIT_DIR
        for shape_name, spin_name in (
            (f"A{model_id}.shape.txt", f"A{model_id}.spin.txt"),
            (f"{model_id}.shape.txt", f"{model_id}.spin.txt"),
            (f"{model_id}/shape.txt", f"{model_id}/spin.txt"),
        ):
            shape, spin = root / shape_name, root / spin_name
            if shape.exists() and spin.exists():
                return shape, spin
        shapes = list(root.rglob(f"*{model_id}*shape*"))
        spins = list(root.rglob(f"*{model_id}*spin*"))
        if shapes and spins:
            return shapes[0], spins[0]
        return None, None

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
    """Parse a DAMIT convex model (native counts-header text or OBJ) → (verts, faces0)."""
    if path.suffix.lower() == ".obj":
        return _parse_obj(path)
    tokens = path.read_text().split()
    nv, nf = int(tokens[0]), int(tokens[1])
    body = tokens[2:]
    verts = np.array(body[: nv * 3], dtype=np.float64).reshape(nv, 3)
    face_vals = np.array(body[nv * 3 : nv * 3 + nf * 3], dtype=np.int64).reshape(nf, 3)
    return verts, face_vals - 1  # DAMIT faces are 1-based


def _parse_obj(path: Path) -> tuple[np.ndarray, np.ndarray]:
    verts, faces = [], []
    for line in path.read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            verts.append([float(x) for x in parts[1:4]])
        elif parts[0] == "f":
            faces.append([int(p.split("/")[0]) - 1 for p in parts[1:4]])
    return np.array(verts, dtype=np.float64), np.array(faces, dtype=np.int64)


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


def _mesh_volume(verts: np.ndarray, faces: np.ndarray) -> float:
    """Signed volume via the divergence (tetrahedron-sum) method; abs for scale."""
    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    return float(abs(np.sum(np.einsum("ij,ij->i", v0, np.cross(v1, v2))) / 6.0))


def _parse_spin(path: Path) -> dict:
    """Read λ, β (deg), P (h), JD₀, φ₀ from a DAMIT spin file.

    Robust to line layout: JD₀ is disambiguated from φ₀ by magnitude (>1e6).
    """
    nums = [float(x) for x in path.read_text().split()]
    if len(nums) < 5:
        raise ValueError(f"{path}: expected ≥5 spin values, got {len(nums)}")
    lam, beta, period = nums[0], nums[1], nums[2]
    rest = nums[3:]
    jd0 = next((x for x in rest if x > 1e6), rest[0])
    phi0 = next((x for x in rest if x <= 1e6), rest[-1])
    return {"lambda": lam, "beta": beta, "period": period, "jd0": jd0, "phi0": phi0}


def _stamp_matches(stamp: Path, shape: Path, spin: Path, diameter_km: float) -> bool:
    if not stamp.exists() or not (stamp.parent / "high.glb").exists():
        return False
    try:
        data = json.loads(stamp.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return (
        data.get("knobs") == config.DAMIT_KNOBS_VERSION
        and data.get("shape_sha") == metadata.sha256_file(shape)
        and data.get("spin_sha") == metadata.sha256_file(spin)
        and data.get("diameter_km") == diameter_km
    )


def _write_stamp(stamp: Path, shape: Path, spin: Path, diameter_km: float) -> None:
    stamp.write_text(
        json.dumps(
            {
                "knobs": config.DAMIT_KNOBS_VERSION,
                "shape_sha": metadata.sha256_file(shape),
                "spin_sha": metadata.sha256_file(spin),
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
    except (TypeError, ValueError):
        return None
