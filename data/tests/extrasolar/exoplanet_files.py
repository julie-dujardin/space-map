"""Synthetic exoplanet downloads: the three catalogues, SIMBAD, Gaia and the
IAU names, written as the providers write them."""

import csv
import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path

from space_map_data.download.providers.stars import gaia_source
from space_map_data.extrasolar.exoplanets.ingest import Inputs
from space_map_data.extrasolar.sources.gaia import (
    ASTROPHYSICAL_COLUMNS,
    FLAME_SPEC_COLUMNS,
    XGBOOST_COLUMNS,
)

ARCHIVE_COLUMNS = (
    "objectid",
    "pl_name",
    "pl_letter",
    "hostid",
    "hostname",
    "hd_name",
    "hip_name",
    "tic_id",
    "sy_name",
    "ra",
    "dec",
    "gaia_dr3_id",
    "gaia_dr2_id",
    "st_spectype",
    "pl_controv_flag",
    "discoverymethod",
    "disc_year",
    "disc_facility",
    "cb_flag",
    "pl_bmassprov",
    "pl_tranmid_systemref",
)
EU_COLUMNS = (
    "name",
    "planet_status",
    "star_name",
    "star_alternate_names",
    "alternate_names",
    "ra",
    "dec",
    "star_sp_type",
    "discovered",
    "detection_type",
    "molecules",
    "mass_measurement_type",
    "radius_measurement_type",
)


def write_csv(path: Path, rows: list[dict], columns: tuple[str, ...] = ()) -> Path:
    header = list(columns)
    for row in rows:
        header += [key for key in row if key not in header]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, header, restval="")
        writer.writeheader()
        writer.writerows(rows)
    return path


@dataclass
class Downloads:
    """Rows of each file; `write` puts them under a directory."""

    archive: list[dict] = field(default_factory=list)
    eu: list[dict] = field(default_factory=list)
    # OEC systems as XML text.
    oec: list[str] = field(default_factory=list)
    # (catalogue, table, kind, object, name, variant, oid)
    simbad_names: list[tuple] = field(default_factory=list)
    # oid → (main_id, otype)
    simbad_basic: dict[str, tuple[str, str]] = field(default_factory=dict)
    simbad_ids: dict[str, list[str]] = field(default_factory=dict)
    simbad_links: list[tuple[str, str]] = field(default_factory=list)
    neighbours: list[dict] = field(default_factory=list)
    orbits: list[dict] = field(default_factory=list)
    gaia_sources: list[dict] = field(default_factory=list)
    fidelity: list[dict] = field(default_factory=list)
    astrophysical: list[dict] = field(default_factory=list)
    flame_spec: list[dict] = field(default_factory=list)
    xgboost: list[dict] = field(default_factory=list)
    names: list[dict] = field(default_factory=list)

    def write(self, root: Path) -> Inputs:
        simbad = root / "simbad"
        write_csv(
            simbad / "names.csv",
            [
                dict(
                    zip(
                        (
                            "catalogue",
                            "table",
                            "kind",
                            "object",
                            "name",
                            "variant",
                            "oid",
                        ),
                        row,
                    )
                )
                for row in self.simbad_names
            ],
            ("catalogue", "table", "kind", "object", "name", "variant", "oid"),
        )
        write_csv(
            simbad / "basic.csv",
            [
                {"main_id": main_id, "otype": otype, "oid": oid}
                for oid, (main_id, otype) in self.simbad_basic.items()
            ],
            ("main_id", "otype", "oid"),
        )
        write_csv(
            simbad / "ids.csv",
            [
                {"oidref": oid, "ids": "|".join(ids)}
                for oid, ids in self.simbad_ids.items()
            ],
            ("oidref", "ids"),
        )
        write_csv(
            simbad / "h_link.csv",
            [{"child": c, "parent": p} for c, p in self.simbad_links],
            ("child", "parent"),
        )
        oec = root / "systems.xml.gz"
        oec.write_bytes(
            gzip.compress(f"<systems>{''.join(self.oec)}</systems>".encode())
        )
        names = root / "names.json"
        names.write_text(json.dumps(self.names))
        return Inputs(
            archive=write_csv(root / "pscomppars.csv", self.archive, ARCHIVE_COLUMNS),
            eu=write_csv(root / "catalog.csv", self.eu, EU_COLUMNS),
            oec=oec,
            simbad=simbad,
            neighbourhood=write_csv(
                root / "dr2_neighbourhood.csv",
                self.neighbours,
                (
                    "dr2_source_id",
                    "dr3_source_id",
                    "angular_distance",
                    "magnitude_difference",
                ),
            ),
            orbits=write_csv(
                root / "nss_two_body_orbit.csv",
                self.orbits,
                (
                    "source_id",
                    "nss_solution_type",
                    "period",
                    "a_thiele_innes",
                    "b_thiele_innes",
                    "f_thiele_innes",
                    "g_thiele_innes",
                ),
            ),
            gaia_source=write_csv(
                root / "gaia_source.csv", self.gaia_sources, gaia_source.COLUMNS
            ),
            fidelity=write_csv(
                root / "fidelity.csv",
                self.fidelity,
                ("source_id", "fidelity_v2", "norm_dg"),
            ),
            astrophysical=write_csv(
                root / "astrophysical_parameters.csv",
                self.astrophysical,
                ("source_id", *ASTROPHYSICAL_COLUMNS),
            ),
            flame_spec=write_csv(
                root / "flame_spec.csv",
                self.flame_spec,
                ("source_id", *FLAME_SPEC_COLUMNS),
            ),
            xgboost=write_csv(
                root / "xgboost.csv", self.xgboost, ("source_id", *XGBOOST_COLUMNS)
            ),
            names=names,
        )


def archive_planet(
    objectid: str, name: str, host: str, hostid: str, ra: float, dec: float, **more
) -> dict:
    """A pscomppars row; `more` holds any other column."""
    return {
        "objectid": objectid,
        "pl_name": name,
        "pl_letter": name.split()[-1],
        "hostid": hostid,
        "hostname": host,
        "sy_name": host,
        "ra": ra,
        "dec": dec,
        "pl_controv_flag": "0",
        "discoverymethod": "Transit",
        "disc_year": "2010",
        "cb_flag": "0",
        "pl_bmassprov": "Mass",
        **more,
    }


def eu_planet(name: str, star: str, ra: float, dec: float, **more) -> dict:
    return {
        "name": name,
        "planet_status": "Confirmed",
        "star_name": star,
        "ra": ra,
        "dec": dec,
        "discovered": "2010",
        "detection_type": "Primary Transit",
        **more,
    }
