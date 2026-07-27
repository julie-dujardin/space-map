"""Checks for the atmosphere derivation chain against published references.

Three layers: per-gas Rayleigh cross sections vs laboratory measurements,
mixture/scale-height derivations vs published atmosphere numbers, and the
assembled export payload's structural invariants.
"""

import math

import pytest

from space_map_data.constants.atmosphere.aerosols import AEROSOLS
from space_map_data.constants.atmosphere.bodies import (
    ATMOSPHERE_BODIES,
    RENDER_WAVELENGTHS_M,
)
from space_map_data.export.atmospheres import build_atmospheres
from space_map_data.export.atmospheres.rayleigh import (
    mean_molar_mass_g_mol,
    rayleigh_beta_per_m,
    rayleigh_cross_section,
    scale_height_km,
)


@pytest.fixture(scope="module")
def payload():
    # The Mie phase precompute makes this expensive (~1 min) — build once.
    return build_atmospheres()


class TestGasCrossSections:
    """Derived per-gas cross sections vs laboratory measurements.

    Measured references: Sneep & Ubachs 2005 (JQSRT 92, 293; CRDS at
    532.2 nm), He et al. 2021 (ACP 21, 14927; broadband cavity-enhanced),
    Dalgarno & Williams 1962 (ApJ 136, 690; ab initio H2, the standard
    source in planetary radiative transfer). Tolerances reflect each
    measurement's error bar.
    """

    MEASURED_CM2 = [
        ("N2", 532.2e-9, 5.10e-27, 0.05),  # ±0.24e-27 → ~5%
        ("CO2", 532.2e-9, 13.3e-27, 0.02),
        ("CO2", 660.0e-9, 5.52e-27, 0.02),
        ("CH4", 532.2e-9, 11.3e-27, 0.02),
        ("CH4", 660.0e-9, 4.68e-27, 0.02),
        ("O2", 532.2e-9, 4.55e-27, 0.03),
        ("O2", 660.0e-9, 1.95e-27, 0.03),
        ("Ar", 532.2e-9, 4.45e-27, 0.03),  # ±0.30e-27
    ]

    @pytest.mark.parametrize("gas,wl,measured,tol", MEASURED_CM2)
    def test_measured_cross_sections(self, gas, wl, measured, tol):
        calc_cm2 = rayleigh_cross_section(gas, wl) * 1e4
        assert calc_cm2 == pytest.approx(measured, rel=tol)

    @pytest.mark.parametrize("wl_nm", [440, 550, 680])
    def test_h2_vs_dalgarno_williams(self, wl_nm):
        angstrom = wl_nm * 10.0
        dw_cm2 = 8.14e-13 / angstrom**4 + 1.28e-6 / angstrom**6 + 1.61 / angstrom**8
        calc_cm2 = rayleigh_cross_section("H2", wl_nm * 1e-9) * 1e4
        # ~3.5% offset between Peck & Huang refractivity and the ab initio
        # values; H2's unmodelled ~2% King correction sits inside this too.
        assert calc_cm2 == pytest.approx(dw_cm2, rel=0.05)


# Earth air at 15 °C / 101.325 kPa, N fixed by those conditions.
_AIR = {"N2": 0.78084, "O2": 0.20946, "Ar": 0.00934, "CO2": 0.0004}
_AIR_P = 101325.0
_AIR_T = 288.15


class TestMixtures:
    """Mixture-level derivations vs published air values."""

    # Bodhaine et al. 1999 (J. Atmos. Ocean. Tech. 16, 1854) table 3: dry-air
    # cross sections at 360 ppm CO2, cm²/molecule.
    BODHAINE_CM2 = [
        (450e-9, 1.0274e-26),
        (500e-9, 6.6614e-27),
        (550e-9, 4.5105e-27),
        (650e-9, 2.2856e-27),
    ]

    @pytest.mark.parametrize("wl,sigma_cm2", BODHAINE_CM2)
    def test_air_beta_vs_bodhaine(self, wl, sigma_cm2):
        beta = rayleigh_beta_per_m(_AIR, _AIR_P, _AIR_T, wl)
        n_ref = _AIR_P / (1.380649e-23 * _AIR_T)
        assert beta == pytest.approx(n_ref * sigma_cm2 * 1e-4, rel=0.01)

    def test_air_beta_vs_bruneton_folklore(self):
        # Bruneton's widely-copied Earth betas (5.802, 13.558, 33.1)e-6 are
        # 1.24062e-6·λ⁻⁴[µm] — rounded n = 1.0003, no depolarisation — and sit
        # ~15-18% above the measurement-anchored derivation. Pin the offset so
        # a regression toward either extreme is caught.
        for wl, bruneton in (
            (680e-9, 5.802e-6),
            (550e-9, 13.558e-6),
            (440e-9, 33.1e-6),
        ):
            beta = rayleigh_beta_per_m(_AIR, _AIR_P, _AIR_T, wl)
            assert 1.10 < bruneton / beta < 1.25

    def test_air_molar_mass(self):
        # Bodhaine et al. 1999 eq. 17 at 360 ppm CO2: 28.9649 g/mol.
        assert mean_molar_mass_g_mol(_AIR) == pytest.approx(28.9649, rel=1e-3)

    def test_earth_scale_height(self):
        # kT/(mg) at 288.15 K ≈ 8.4 km — the value Earth renderers use.
        h = scale_height_km(mean_molar_mass_g_mol(_AIR), _AIR_T, 9.80665)
        assert h == pytest.approx(8.4, abs=0.1)


class TestBodies:
    """Per-body derivations vs published scale heights / mean molar masses."""

    # NSSDCA planetary fact sheets (2024-2025 revisions), surface / 1-bar
    # check values. Our derivation uses the *render* reference level, so each
    # row re-evaluates at the fact sheet's own conditions (T, effective g) —
    # only the composition comes from our constants. Jupiter's tolerance is
    # wider because NSSDCA's He row (10.2%, Voyager-era) predates the Galileo
    # probe's 13.59% our constants adopt.
    NSSDCA = [
        # (body, T_k, g_eff, published_H_km, published_M_g_mol, rel_tol)
        ("naif-499", 214.0, 3.73, 11.0, 43.49, 0.03),  # Mars datum
        ("naif-299", 737.0, 8.87, 15.9, 43.45, 0.03),  # Venus surface
        ("naif-799", 76.0, 8.69, 27.7, 2.64, 0.03),  # Uranus 1 bar
        ("naif-599", 165.0, 23.12, 27.0, 2.22, 0.07),  # Jupiter 1 bar
    ]

    @pytest.mark.parametrize("object_id,t_k,g,h_km,m_pub,tol", NSSDCA)
    def test_scale_heights_at_published_conditions(
        self, object_id, t_k, g, h_km, m_pub, tol
    ):
        body = ATMOSPHERE_BODIES[object_id]
        molar = mean_molar_mass_g_mol(body.composition)
        assert molar == pytest.approx(m_pub, rel=tol)
        assert scale_height_km(molar, t_k, g) == pytest.approx(h_km, rel=tol)

    def test_titan_scale_height_at_huygens_conditions(self):
        # No NSSDCA atmosphere block exists for Titan; check the derived
        # surface scale height against HASI/GCMS numbers directly:
        # kT/(mg) at 93.65 K (Fulchignoni et al. 2005) with the GCMS mean
        # molar mass (~27.3, N2 + 5.65% CH4) ≈ 21 km.
        body = ATMOSPHERE_BODIES["naif-606"]
        molar = mean_molar_mass_g_mol(body.composition)
        assert molar == pytest.approx(27.3, rel=0.01)
        assert scale_height_km(molar, 93.65, 1.35) == pytest.approx(21.1, rel=0.02)

    def test_earth_ozone_band_vs_bruneton(self, payload):
        # Bruneton's reference implementation carries peak ozone absorption
        # (0.650, 1.881, 0.085)e-3/km for the same 300 DU tent. His values
        # are CIE-band-averaged; ours are Serdyuchenko/Gorshelev point
        # samples at 680/550/440 nm, so agreement is ~±15% (worst in blue,
        # where the Chappuis edge is steep).
        entry = payload["bodies"]["naif-399"]
        for ours, bruneton in zip(
            entry["absorption_per_km"], (0.650e-3, 1.881e-3, 0.085e-3)
        ):
            assert ours == pytest.approx(bruneton, rel=0.20)


class TestPayload:
    """Structural invariants of the assembled atmospheres.json payload."""

    def test_expected_bodies(self, payload):
        assert set(payload["bodies"]) == {
            "naif-299",
            "naif-399",
            "naif-499",
            "naif-599",
            "naif-606",
            "naif-699",
            "naif-799",
            "naif-801",
            "naif-899",
            "naif-999",
        }

    def test_every_body_has_a_phase_lut(self, payload):
        n = payload["phase_n"]
        for object_id, entry in payload["bodies"].items():
            lut = payload["phases"].get(entry["phase"])
            assert lut is not None, object_id
            assert len(lut) == 3 * n

    def test_phase_luts_normalised(self, payload):
        # Each channel integrates to ~1 over the sphere on the warped grid.
        n = payload["phase_n"]
        thetas = [math.pi * (i / (n - 1)) ** 2 for i in range(n)]
        for key, lut in payload["phases"].items():
            for channel in range(3):
                block = lut[channel * n : (channel + 1) * n]
                integral = 0.0
                for i in range(n - 1):
                    mid = 0.5 * (
                        block[i] * math.sin(thetas[i])
                        + block[i + 1] * math.sin(thetas[i + 1])
                    )
                    integral += 2.0 * math.pi * mid * (thetas[i + 1] - thetas[i])
                assert integral == pytest.approx(1.0, rel=0.02), (key, channel)

    def test_positive_finite_coefficients(self, payload):
        for object_id, entry in payload["bodies"].items():
            for field in (
                "rayleigh_scatter_per_km",
                "mie_scatter_per_km",
                "mie_absorption_per_km",
                "absorption_per_km",
            ):
                for v in entry[field]:
                    assert v >= 0.0 and math.isfinite(v), (object_id, field)
            assert entry["rayleigh_scale_height_km"] > 0
            assert entry["mie_scale_height_km"] > 0
            assert entry["top_altitude_km"] > 0

    def test_aerosol_keys_resolve(self):
        from space_map_data.constants.atmosphere.aerosols import PHASE_MODELS

        for object_id, body in ATMOSPHERE_BODIES.items():
            assert body.aerosol in AEROSOLS, object_id
            assert AEROSOLS[body.aerosol].phase in PHASE_MODELS, object_id

    def test_render_wavelengths_are_bruneton_rgb(self):
        assert list(RENDER_WAVELENGTHS_M.values()) == [680e-9, 550e-9, 440e-9]
