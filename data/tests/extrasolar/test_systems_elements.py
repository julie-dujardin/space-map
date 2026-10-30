"""Each orbit source's orbit as the secondary's about the primary, tested on
α Cen AB, Kepler-16 and the eclipses of Kepler-34 and -35."""

import math

import pyarrow as pa
import pyarrow.compute as pc
import pytest

from space_map_data.constants.stars import binaries
from space_map_data.extrasolar import frame
from space_map_data.extrasolar.systems import elements, orbits
from tests.download.orbit_catalogue_files import MSC_LINES
from tests.extrasolar.systems_fakes import (
    KEPLER_16,
    KEPLER_16_GAIA,
    catalogue_orbits,
    msc_orbit_rows,
)

# Rows of the MSC's orb.tsv, as published. 00042-5055 Ab,Ac has velocities
# and the inclination of its eclipses; 16555-0820 Ba,Bb is a copy of ORB6.
# Neither has an angular a.
MSC_ECLIPSING = "00042-5055|Ab,Ac   |      0.5703|58354.2542| 0.001|  0.0000|  0.00|140.00| 87.96|135.10|172.85|    0.00| |d|2024A&A...686A..27R           "
# 07346+3153 Ba,Bb has velocities and a node, and no a.
MSC_COMBINED = "07346+3153|Ba,Bb   |      2.9284|56705.4940| 0.000|  0.0000|106.47|  0.00|110.55| 32.09|  0.00|    0.00| |d|2022ApJ...941....8T           "
MSC_VB6 = "16555-0820|Ba,Bb   |      0.0081| 1998.2874| 0.021|  0.0000|  0.00|150.00|164.18|  0.00|  0.00|    0.00| |y|VB6_Sgr2000 Gl_644Ba,B Gr.8   "
RR_CAE = "gaia/dr3/4788741548375134336"


def _angle(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _kepler(mean: float, e: float) -> float:
    """The true anomaly in degrees at a mean anomaly in degrees."""
    m = math.radians(mean)
    anomaly = m
    for _ in range(50):
        anomaly -= (anomaly - e * math.sin(anomaly) - m) / (1 - e * math.cos(anomaly))
    nu = 2 * math.atan2(
        math.sqrt(1 + e) * math.sin(anomaly / 2),
        math.sqrt(1 - e) * math.cos(anomaly / 2),
    )
    return math.degrees(nu) % 360


def _known(value: float | None) -> float:
    assert value is not None
    return value


def _elements(table: pa.Table) -> list[elements.Elements]:
    found = [elements.catalogue_elements(row) for row in table.to_pylist()]
    return [item for item in found if item is not None]


class TestConventions:
    """Each source's orbit as the secondary's about the primary."""

    def test_alpha_cen_has_one_omega_in_every_source(self, tmp_path):
        """ORB6 and the visual MSC orbit give the secondary's ω, SB9 and SBX
        the primary's."""
        table = catalogue_orbits(tmp_path)
        rows = table.filter(pc.equal(table["system"], "14396-6050"))
        found = {
            (item.source, item.reference): item
            for item in _elements(rows)
            if _known(item.period) < 40_000
        }
        omegas = [_known(item.arg_periastron) for item in found.values()]
        assert len(omegas) == 4
        assert all(_angle(omega, 232.0) < 1.0 for omega in omegas)
        visual = found[("msc", "VB6_Pbx2016 RHD_1AB Gr.2")]
        assert (visual.node, visual.arg_periastron) == (204.75, 232.30)
        assert not visual.omega_fixed and not visual.node_ascending
        spectroscopic = found[("msc", "SB9_815 2002A&A...386..280P")]
        assert spectroscopic.arg_periastron == pytest.approx(51.65 + 180)
        assert spectroscopic.omega_fixed
        assert (spectroscopic.k1, spectroscopic.k2) == (4.61, 5.45)

    def test_kepler_16_paper_and_gaia_agree(self):
        literature, _ = orbits.read_literature()
        row = next(
            r for r in literature.to_pylist() if r["system"] == "/".join(KEPLER_16)
        )
        paper = elements.catalogue_elements(row)
        gaia = elements.gaia_elements(KEPLER_16_GAIA, 0)
        assert paper is not None and gaia is not None
        # Doyle et al.'s ω is the primary's.
        assert paper.arg_periastron == pytest.approx(263.464 - 180)
        assert paper.phase == elements.OSCULATING
        assert paper.mean_anomaly == pytest.approx((92.352 - 263.464) % 360)
        assert gaia.arg_periastron is not None and gaia.node is not None
        assert _angle(_known(paper.arg_periastron), gaia.arg_periastron) < 3
        assert gaia.node == pytest.approx(8.2, abs=0.1) and gaia.node_ascending
        assert gaia.inclination == pytest.approx(85.8, abs=0.1)
        assert gaia.a_au == pytest.approx(paper.a_au, rel=0.02)

    @pytest.mark.parametrize("name", ["Kepler-16", "Kepler-34", "Kepler-35"])
    def test_the_secondary_is_in_front_at_the_primary_eclipse(self, name):
        """The epoch of Kepler-16's fit and the eclipses of Kepler-34 and -35
        put the secondary in front of the primary, at ω + ν = 270°."""
        literature, _ = orbits.read_literature()
        keys = {
            "Kepler-16": KEPLER_16,
            "Kepler-34": ("gaia", "dr3", "2079692678777827712"),
            "Kepler-35": ("gaia", "dr3", "2128155371757730816"),
        }
        row = next(
            r for r in literature.to_pylist() if r["system"] == "/".join(keys[name])
        )
        item = elements.catalogue_elements(row)
        assert item is not None and item.mean_anomaly is not None
        eclipse = binaries.BINARIES[keys[name]].epoch
        when = eclipse.value if eclipse else row["osculating_epoch"]
        epoch, period = _known(item.epoch), _known(item.period)
        mean = item.mean_anomaly + 360 * (when - epoch) / period
        nu = _kepler(mean % 360, _known(item.eccentricity))
        assert _angle(_known(item.arg_periastron) + nu, 270.0) < 0.5

    def test_an_msc_orbit_with_no_angular_a_gives_the_primarys_omega(self, tmp_path):
        """An inclination does not make it a visual orbit."""
        (item,) = _elements(msc_orbit_rows(tmp_path, MSC_ECLIPSING))
        assert item.inclination == 87.96
        assert item.arg_periastron == pytest.approx(140.0 + 180)
        assert item.omega_fixed

    def test_velocities_tell_the_ascending_node_with_no_a(self, tmp_path):
        (item,) = _elements(msc_orbit_rows(tmp_path, MSC_COMBINED))
        assert (item.node, item.node_ascending) == (106.47, True)

    def test_proxima_has_a_visual_orbit_whose_a_is_too_large_to_print(self, tmp_path):
        (item,) = _elements(
            msc_orbit_rows(
                tmp_path, next(line for line in MSC_LINES if "|AB,C" in line)
            )
        )
        assert item.arg_periastron == 70.0 and not item.omega_fixed

    def test_a_copy_of_orb6_with_no_a_is_a_visual_orbit(self, tmp_path):
        (item,) = _elements(msc_orbit_rows(tmp_path, MSC_VB6))
        assert item.arg_periastron == 150.0 and not item.omega_fixed

    def test_an_assumed_omega_is_not_fixed(self):
        """RR Cae: Maxted et al. 2007 give e = 0 and no ω."""
        literature, _ = orbits.read_literature()
        row = next(r for r in literature.to_pylist() if r["system"] == RR_CAE)
        item = elements.catalogue_elements(row)
        assert item is not None and "arg_periastron" in item.assumed
        assert item.arg_periastron == elements.CIRCULAR_OMEGA
        assert not item.omega_fixed

    def test_a_secondary_omega_of_a_paper_stays(self):
        literature, _ = orbits.read_literature()
        row = next(
            r
            for r in literature.to_pylist()
            if r["arg_periastron_of"] == binaries.SECONDARY
        )
        item = elements.catalogue_elements(row)
        assert item is not None and item.arg_periastron == row["arg_periastron"]

    def test_thiele_innes_both_ways(self):
        a0, i, node, omega = 3.0, 60.0, 30.0, 100.0
        p, q = frame.orbit_axes(i, node, omega)
        # North and east of P and Q, times a0: A, B and F, G.
        a, b, f, g = a0 * p[0], a0 * p[1], a0 * q[0], a0 * q[1]
        assert elements.thiele_innes(a, b, f, g) == pytest.approx((a0, i, node, omega))

    def test_a_photocentre_needs_the_flux_ratio(self):
        orbit = KEPLER_16_GAIA | {
            "nss_solution_type": "Orbital",
            "c_thiele_innes": None,
            "h_thiele_innes": None,
        }
        without = elements.gaia_elements(orbit | {"fluxratio": None}, 0)
        assert without is not None
        assert without.arg_periastron is None and without.a_au is None
        assert without.inclination is not None and without.node is not None
        assert not without.node_ascending
        with_flux = elements.gaia_elements(orbit, 0)
        assert with_flux is not None and with_flux.a_au is not None
        gaia = KEPLER_16_GAIA
        a, b, f, g = (gaia[f"{name}_thiele_innes"] for name in "abfg")
        a0, _, _, omega = elements.thiele_innes(a, b, f, g)
        share = gaia["m2"] / (gaia["m1"] + gaia["m2"])
        light = gaia["fluxratio"] / (1 + gaia["fluxratio"])
        assert with_flux.a_au == pytest.approx(a0 / (share - light) / 13.19352913)
        assert with_flux.arg_periastron == pytest.approx((omega + 180) % 360)

    def test_a_spectroscopic_orbit_has_no_inclination(self):
        item = elements.gaia_elements(
            KEPLER_16_GAIA | {"nss_solution_type": "SB1", "arg_periastron": 10.0}, 0
        )
        assert item is not None
        assert item.inclination is None and item.arg_periastron == 190.0
