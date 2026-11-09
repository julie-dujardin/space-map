"""Tests for space_map_data.export.objects.body_mass."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from space_map_data.constants import body_literature
from space_map_data.download.providers.spice.probes.target_bodies import (
    GM_PATCH_CONTENT,
    GM_SYSTEMS_CONTENT,
)
from space_map_data.export.objects.body_mass import (
    BodyMass,
    BodyMasses,
    JPLGm,
    Satellite,
    bundle_fields,
    catalogue_masses,
    jpl_mass,
    jpl_masses,
    kernel_masses,
    load_body_masses,
    moon_satellites,
    same_fit,
)
from space_map_data.export.objects.wikidata_claims import (
    referenced_mass_kg_from_claims,
)
from space_map_data.export.systems import GmTable
from space_map_data.export.wikidata import WikidataEntity
from space_map_data.ingest.providers.objects.sbdb import mass_kg_from_gm
from space_map_data.models.object import (
    SBDB,
    AsterSatMoon,
    JohnstonSystem,
    JPLSatellitePhysical,
    Object,
    ObjectType,
    SsODNet,
)
from space_map_data.models.object.sbdb import OrbitClass
from tests.conftest import EntityStub


def _masses(wikidata: dict[str, float] | None = None, **kwargs) -> BodyMasses:
    return BodyMasses(wikidata_kg=lambda qid: (wikidata or {}).get(qid), **kwargs)


def _gm_table(
    rows: dict[int, tuple[float, str]],
    primaries: dict[int, tuple[float, str]] | None = None,
) -> GmTable:
    return GmTable(
        {naif_id: gm for naif_id, (gm, _) in rows.items()},
        {naif_id: kernel for naif_id, (_, kernel) in rows.items()},
        primaries or {},
    )


class TestJPLMass:
    """A JPL GM is nominal when the table cannot tell it from nothing."""

    def test_a_measured_gm(self):
        """Io, JUP365."""
        mass = jpl_mass(JPLGm("5959.91547", 0.00135, False, "JUP365"))
        assert mass == BodyMass(
            mass_kg_from_gm(5959.91547), "jpl_satellite_physical", False, "JUP365"
        )

    def test_a_sigma_as_large_as_the_gm_is_nominal(self):
        """Adrastea: 0.00014 ± 0.00020."""
        mass = jpl_mass(JPLGm("0.00014", 0.0002, False, "JUP365"))
        assert mass is not None and mass.nominal

    def test_an_upper_limit_is_nominal(self):
        """Kerberos: <0.0002."""
        mass = jpl_mass(JPLGm("0.0002", None, True, "PLU060"))
        assert mass is not None and mass.nominal
        assert mass.kg == pytest.approx(mass_kg_from_gm(0.0002))

    def test_a_gm_with_no_sigma_is_nominal(self):
        mass = jpl_mass(JPLGm("0.0015", None, False, "PLU060"))
        assert mass is not None and mass.nominal

    def test_a_gm_of_zero_is_no_value(self):
        """Nereid: 0.00000 in NEP101."""
        assert jpl_mass(JPLGm("0.00000", 0.0, False, "NEP101")) is None

    def test_no_gm_is_no_value(self):
        assert jpl_mass(JPLGm(None, None, False, None)) is None

    def test_a_rounded_copy_of_gm_de440_takes_its_digits(self):
        """Miranda: the table prints 4.3 ± 0.2, gm_de440 has 4.3195."""
        mass = jpl_mass(JPLGm("4.3", 0.2, False, "URA111"), 4.3195168992321005)
        assert mass == BodyMass(
            mass_kg_from_gm(4.3195168992321005), "pck", False, "gm_de440.tpc"
        )

    def test_the_table_still_says_nominal(self):
        """Despina: 0.11673 ± 0.25 in the table."""
        mass = jpl_mass(JPLGm("0.11673", 0.25, False, "NEP097"), 0.1167318403814998)
        assert mass is not None and mass.nominal and mass.source == "pck"

    def test_another_fit_keeps_the_table(self):
        """Nix: PLU060 0.0015 in the table, PLU058 0.00305 in gm_de440."""
        mass = jpl_mass(JPLGm("0.0015", 0.0005, False, "PLU060"), 0.0030481756)
        assert mass == BodyMass(
            mass_kg_from_gm(0.0015), "jpl_satellite_physical", False, "PLU060"
        )


class TestSameFit:
    """A printed value is a copy when it is the full value cut or rounded."""

    @pytest.mark.parametrize(
        ("printed", "full"),
        [
            ("4.3", 4.3195168992321005),  # Miranda, rounded
            ("0.0007087", 0.0007087546066894452),  # Phobos, cut
            ("0.0000962", 9.615569648120313e-05),  # Deimos
            ("4902.8", 4902.800118457549),  # the Moon
            ("65", 65.43),  # a whole number keeps no decimal
        ],
    )
    def test_a_copy(self, printed, full):
        assert same_fit(printed, full)

    @pytest.mark.parametrize(
        ("printed", "full"),
        [
            ("106.1", 105.8799888601881),  # Charon, PLU060 vs PLU058
            ("0.12662", 0.1265765099012197),  # Janus
            ("0.002", 0.003211039206155255),  # Hydra
            ("4.30", 4.3195168992321005),  # a trailing zero is a digit
        ],
    )
    def test_another_fit(self, printed, full):
        assert not same_fit(printed, full)


class TestKernelMasses:
    """A kernel GM ranks by the kernel that sets it, and is credited to whoever
    made the value."""

    def test_the_kernels_split_three_ways(self):
        ephemeris, others, nominal = kernel_masses(
            _gm_table(
                {
                    999: (869.3, "gm_de440.tpc"),
                    2162173: (2.98e-8, "ryugu_v10.tpc"),
                    507: (0.13, "Gravity.tpc"),
                    1000036: (1.5e-5, "smallbody_gm_estimates.tpc"),
                }
            )
        )
        assert ephemeris == {
            999: BodyMass(mass_kg_from_gm(869.3), "pck", False, "gm_de440.tpc")
        }
        assert others == {
            2162173: BodyMass(mass_kg_from_gm(2.98e-8), "pck", False, "ryugu_v10.tpc")
        }
        assert nominal == {
            507: BodyMass(mass_kg_from_gm(0.13), "pck", True, "Gravity.tpc"),
            1000036: BodyMass(mass_kg_from_gm(1.5e-5), "estimate", True),
        }

    def test_a_gm_of_the_papers_is_credited_to_its_paper(self):
        """Bennu: Scheeres et al. 2019, not NAIF."""
        _, others, _ = kernel_masses(
            _gm_table({2101955: (4.892e-9, "smallbody_gm_patch.tpc")})
        )
        scheeres = body_literature.REFERENCES["scheeres_2019"]._asdict()
        assert others[2101955] == BodyMass(
            mass_kg_from_gm(4.892e-9), "literature", reference=scheeres
        )

    def test_the_papers_are_those_of_the_kernels(self):
        """`target_bodies` writes every GM of the papers into its kernels."""
        for naif_id, gm in body_literature.GMS.items():
            assert f"BODY{gm.spice_id or naif_id}_GM = ( {gm.gm} )" in GM_PATCH_CONTENT
        for naif_id, gm in body_literature.SYSTEM_GMS.items():
            assert (
                f"BODY{gm.spice_id or naif_id}_GM = ( {gm.gm} )" in GM_SYSTEMS_CONTENT
            )

    def test_a_binary_primary_takes_its_own_gm(self):
        """Orcus: system 42.03, primary 38.5596 in gm_de440."""
        ephemeris, _, _ = kernel_masses(
            _gm_table(
                {2090482: (42.03, "gm_de440.tpc")},
                {2090482: (38.5596, "gm_de440.tpc")},
            )
        )
        assert ephemeris[2090482] == BodyMass(
            mass_kg_from_gm(38.5596), "pck", False, "gm_de440.tpc"
        )

    def test_a_primary_gm_equal_to_the_system_gm_is_a_system_mass(self):
        """612095: system and primary 0.0268 in gm_de440, the moon has GM 0."""
        ephemeris, _, _ = kernel_masses(
            _gm_table(
                {2612095: (0.0268, "gm_de440.tpc")},
                {2612095: (0.0268, "gm_de440.tpc")},
            )
        )
        assert ephemeris[2612095] == BodyMass(
            mass_kg_from_gm(0.0268), "pck", False, "gm_de440.tpc", system=True
        )

    def test_a_systems_kernel(self):
        """Patroclus: the binary orbit of Marchis et al. 2006."""
        _, others, _ = kernel_masses(
            _gm_table({2000617: (9.08e-2, "smallbody_gm_systems.tpc")})
        )
        marchis = body_literature.REFERENCES["marchis_2006"]._asdict()
        assert others[2000617] == BodyMass(
            mass_kg_from_gm(9.08e-2), "literature", reference=marchis, system=True
        )

    def test_a_primary_gm_of_a_systems_kernel_body_is_its_own(self):
        """A kernel that gives Patroclus apart from its system."""
        _, others, _ = kernel_masses(
            _gm_table(
                {2000617: (9.08e-2, "smallbody_gm_systems.tpc")},
                {2000617: (8.0e-2, "lcy_patroclus.tpc")},
            )
        )
        assert others[2000617] == BodyMass(
            mass_kg_from_gm(8.0e-2), "pck", False, "lcy_patroclus.tpc"
        )

    def test_the_ssb_row_has_no_kernel(self):
        _, others, _ = kernel_masses(_gm_table({0: (1.3e11, "")}))
        assert others[0].reference is None


class TestPick:
    """JPL, gm_de440, other kernels, the catalogues, the nominal catalogue
    values, the nominal kernels, then Wikidata."""

    def test_jpl_beats_gm_de440(self):
        """Nix: PLU060 0.0015 in the table, PLU058 0.00305 in gm_de440."""
        jpl = BodyMass(
            mass_kg_from_gm(0.0015), "jpl_satellite_physical", False, "PLU060"
        )
        masses = _masses(
            jpl={902: jpl},
            ephemeris={
                902: BodyMass(mass_kg_from_gm(0.00305), "pck", False, "gm_de440.tpc")
            },
        )
        assert masses.pick("naif-902", 902, None, ObjectType.moon) == jpl

    def test_a_nominal_jpl_value_still_comes_first(self):
        jpl = BodyMass(
            mass_kg_from_gm(0.0002), "jpl_satellite_physical", True, "PLU060"
        )
        masses = _masses(jpl={904: jpl}, wikidata={"Q1": 1.0e16})
        assert masses.pick("naif-904", 904, "Q1", ObjectType.moon) == jpl

    def test_gm_de440_beats_another_kernel(self):
        ours = BodyMass(1.0, "pck", False, "gm_de440.tpc")
        masses = _masses(
            ephemeris={2000001: ours},
            kernels={2000001: BodyMass(2.0, "pck", False, "dawn.tpc")},
        )
        assert (
            masses.pick("spkid-20000001", 2000001, None, ObjectType.dwarf_planet)
            == ours
        )

    def test_a_kernel_beats_the_catalogues(self):
        ours = BodyMass(1.0, "pck", False, "bennu_v17.tpc")
        masses = _masses(
            kernels={2101955: ours},
            catalogues={"spkid-20101955": BodyMass(2.0, "sbdb")},
        )
        assert masses.pick("spkid-20101955", 2101955, None, ObjectType.asteroid) == ours

    def test_a_catalogue_beats_wikidata(self):
        ours = BodyMass(1.75e21, "ssodnet")
        masses = _masses(catalogues={"spkid-20225088": ours}, wikidata={"Q1": 5e22})
        assert (
            masses.pick("spkid-20225088", 2225088, "Q1", ObjectType.dwarf_planet)
            == ours
        )

    def test_a_nominal_catalogue_beats_a_nominal_kernel(self):
        ours = BodyMass(2.0, "johnston", True)
        masses = _masses(
            nominal_catalogues={"spkid-20486958": ours},
            nominal_kernels={2486958: BodyMass(1.0, "estimate", True)},
        )
        assert (
            masses.pick("spkid-20486958", 2486958, None, ObjectType.asteroid_tno)
            == ours
        )

    def test_a_measured_catalogue_beats_a_nominal_one(self):
        """A SsODNet mass with no error ranks below a Johnston measurement."""
        ours = BodyMass(3.0, "johnston", system=True)
        masses = _masses(
            catalogues={"spkid-20003548": ours},
            nominal_catalogues={"spkid-20003548": BodyMass(2.0, "ssodnet", True)},
        )
        assert masses.pick("spkid-20003548", None, None, ObjectType.asteroid) == ours

    def test_a_nominal_catalogue_beats_wikidata(self):
        ours = BodyMass(4.85e11, "ssodnet", True)
        masses = _masses(
            nominal_catalogues={"spkid-20069230": ours}, wikidata={"Q1": 5.0e11}
        )
        assert masses.pick("spkid-20069230", None, "Q1", ObjectType.asteroid) == ours

    def test_a_nominal_kernel_beats_wikidata(self):
        """Halley: Wikidata's referenced 220 Tg is 1000 times too low."""
        halley = BodyMass(2.2e14, "estimate", True)
        masses = _masses(nominal_kernels={1000036: halley}, wikidata={"Q1": 2.2e11})
        assert masses.pick("spkid-1000036", 1000036, "Q1", ObjectType.comet) == halley

    def test_wikidata_is_the_last_fallback(self):
        masses = _masses(wikidata={"Q1": 2.2e11})
        assert masses.pick(
            "spkid-1000036", 1000036, "Q1", ObjectType.comet
        ) == BodyMass(2.2e11, "wikidata")

    def test_a_barycentre_has_no_mass(self):
        """naif-5: the GM of the Jovian system is not a body mass."""
        masses = _masses(ephemeris={5: BodyMass(1.9e27, "pck", False, "gm_de440.tpc")})
        assert masses.pick("naif-5", 5, None, ObjectType.barycenter) is None

    def test_no_source_gives_none(self):
        assert _masses().pick("naif-716", 716, "Q1", ObjectType.moon) is None
        assert BodyMasses().pick("naif-716", 716, "Q1", ObjectType.moon) is None

    @pytest.mark.parametrize(
        "object_type",
        [ObjectType.spacecraft, ObjectType.debris, ObjectType.undocumented],
    )
    def test_a_craft_never_gets_a_mass(self, object_type):
        masses = _masses(
            ephemeris={-98: BodyMass(1.0, "pck")}, wikidata={"Q160398": 478.0}
        )
        assert masses.pick("probe-98", -98, "Q160398", object_type) is None

    def test_of_reads_the_object_ids(self):
        masses = _masses(wikidata={"Q18481": 1.0e17})
        obj = Object(
            id="naif-716", naif_id=716, wikidata_qid="Q18481", object_type="moon"
        )
        assert masses.of(obj) == BodyMass(1.0e17, "wikidata")


class TestCatalogueMasses:
    """SBDB, SsODNet, AsterSat, then Johnston, from the ingested tables."""

    @staticmethod
    def _body(session: Session, object_id: str, object_type=ObjectType.asteroid):
        session.add(Object(id=object_id, object_type=object_type))

    @staticmethod
    def _astersat(parent: str, gm: float) -> AsterSatMoon:
        return AsterSatMoon(
            object_id="spkid-120225088",
            parent_object_id=parent,
            astersat_id="AN0225088",
            system_label="(225088)Gonggong",
            satellite_label="companion",
            frame="geoequat J2000",
            epoch_mjd=55140.0,
            a_km=23672.61,
            e=0.34,
            i=92.7,
            om=205.3,
            w=99.8,
            ma=54.4,
            n=83.7,
            per_d=4.3,
            gm=gm,
        )

    def test_sbdb_beats_ssodnet(self, session: Session):
        self._body(session, "spkid-20000004")
        session.add(
            SBDB(
                spkid="20000004",
                object_id="spkid-20000004",
                class_=OrbitClass.MBA,
                GM=17.29,
            )
        )
        session.add(
            SsODNet(object_id="spkid-20000004", mass_kg=2.6e20, mass_kg_sigma=1e18)
        )
        session.commit()
        assert catalogue_masses(session)[0]["spkid-20000004"] == BodyMass(
            mass_kg_from_gm(17.29), "sbdb"
        )

    def test_ssodnet_beats_astersat(self, session: Session):
        """Gonggong: SsODNet 1.75e21 kg, AsterSat's 4.3 d fit 5.68e22."""
        self._body(session, "spkid-20225088", ObjectType.dwarf_planet)
        self._body(session, "spkid-120225088", ObjectType.moon)
        session.add(
            SsODNet(object_id="spkid-20225088", mass_kg=1.7535e21, mass_kg_sigma=4.3e19)
        )
        session.add(self._astersat("spkid-20225088", 3792.71))
        session.commit()
        assert catalogue_masses(session)[0]["spkid-20225088"] == BodyMass(
            1.7535e21, "ssodnet"
        )

    def test_a_ssodnet_mass_with_no_error_is_nominal(self, session: Session):
        """Hermes: the BFT gives no error."""
        self._body(session, "spkid-20069230")
        session.add(SsODNet(object_id="spkid-20069230", mass_kg=4.85e11))
        session.commit()
        measured, nominal = catalogue_masses(session)
        assert measured == {}
        assert nominal["spkid-20069230"] == BodyMass(4.85e11, "ssodnet", True)

    def test_astersat_beats_johnston(self, session: Session):
        self._body(session, "spkid-20225088", ObjectType.dwarf_planet)
        self._body(session, "spkid-120225088", ObjectType.moon)
        session.add(self._astersat("spkid-20225088", 3792.71))
        session.add(
            JohnstonSystem(
                object_id="spkid-20225088",
                page="am-225088",
                designation="Gonggong",
                mass_kg=1.75e21,
            )
        )
        session.commit()
        astersat = catalogue_masses(session)[0]["spkid-20225088"]
        assert astersat == BodyMass(mass_kg_from_gm(3792.71), "astersat", system=True)

    @pytest.mark.parametrize("nominal", [False, True])
    def test_johnston_carries_its_flag(self, session: Session, nominal):
        """Thymbraeus. A Johnston mass is that of the system."""
        self._body(session, "spkid-20017365")
        session.add(
            JohnstonSystem(
                object_id="spkid-20017365",
                page="am-17365",
                designation="(17365) Thymbraeus",
                mass_kg=2.26e16,
                mass_kg_nominal=nominal,
            )
        )
        session.commit()
        measured, nominal_masses = catalogue_masses(session)
        masses = nominal_masses if nominal else measured
        assert masses["spkid-20017365"] == BodyMass(
            2.26e16, "johnston", nominal, system=True
        )

    def test_a_zero_or_missing_mass_is_skipped(self, session: Session):
        self._body(session, "spkid-20000004")
        session.add(
            SBDB(
                spkid="20000004",
                object_id="spkid-20000004",
                class_=OrbitClass.MBA,
                GM=0.0,
            )
        )
        session.add(SsODNet(object_id="spkid-20000004", diameter_km=525.0))
        session.commit()
        assert catalogue_masses(session) == ({}, {})


class TestJPLMasses:
    def test_rows_by_naif_id_without_zero(self, session: Session):
        session.add(Object(id="naif-902", naif_id=902, object_type=ObjectType.moon))
        session.add(Object(id="naif-802", naif_id=802, object_type=ObjectType.moon))
        session.add(
            JPLSatellitePhysical(
                object_id="naif-902",
                naif_id=902,
                gm_km3_s2="0.0015",
                gm_sigma_km3_s2=0.0005,
                ephemeris="PLU060",
            )
        )
        session.add(
            JPLSatellitePhysical(
                object_id="naif-802",
                naif_id=802,
                gm_km3_s2="0.00000",
                gm_sigma_km3_s2=0.0,
                ephemeris="NEP101",
            )
        )
        session.commit()
        assert jpl_masses(session, {}) == {
            902: BodyMass(
                mass_kg_from_gm(0.0015), "jpl_satellite_physical", False, "PLU060"
            )
        }


def _mass_statement(amount: str, references: list[dict]) -> dict:
    # Q11570 is the kilogram.
    value = {"amount": amount, "unit": "http://www.wikidata.org/entity/Q11570"}
    snak = {"snaktype": "value", "datavalue": {"value": value, "type": "quantity"}}
    return {
        "mainsnak": snak,
        "rank": "normal",
        "type": "statement",
        "references": references,
    }


def _stated_in(qid: str) -> dict:
    return {"snaks": {"P248": [{"datavalue": {"value": {"id": qid}}}]}}


def _imported_from(qid: str) -> dict:
    return {"snaks": {"P143": [{"datavalue": {"value": {"id": qid}}}]}}


def _reference_url(url: str) -> dict:
    return {"snaks": {"P854": [{"datavalue": {"value": url}}]}}


def _units() -> MagicMock:
    units = MagicMock()
    units.convert_to_base.side_effect = lambda value, unit, expected_type: value
    return units


class TestReferencedMass:
    """A Wikidata mass counts only with a reference that names a source."""

    @pytest.mark.parametrize(
        "reference", [_stated_in("Q1"), _reference_url("https://ssd.jpl.nasa.gov/")]
    )
    def test_a_cited_mass_counts(self, reference):
        claims = {"P2067": [_mass_statement("+4.0e21", [reference])]}
        assert referenced_mass_kg_from_claims(claims, _units(), "Q1") == 4.0e21

    @pytest.mark.parametrize("references", [[], [_imported_from("Q328")]])
    def test_an_uncited_mass_does_not(self, references):
        """Haumea's 4.006 Zg is cited to nothing but a Wikipedia."""
        claims = {"P2067": [_mass_statement("+4.006e18", references)]}
        assert referenced_mass_kg_from_claims(claims, _units(), "Q1") is None

    def test_the_cited_one_of_two(self):
        claims = {
            "P2067": [
                _mass_statement("+4.006e18", [_imported_from("Q328")]),
                _mass_statement("+4.0e21", [_stated_in("Q1")]),
            ]
        }
        assert referenced_mass_kg_from_claims(claims, _units(), "Q1") == 4.0e21


class TestLoadBodyMasses:
    def test_the_kernel_gms_and_wikidata(self, session: Session):
        claims = {"P2067": [_mass_statement("+1.0e17", [_stated_in("Q2")])]}
        entity = WikidataEntity(
            labels={}, descriptions={}, aliases={}, claims=claims, sitelinks={}
        )
        masses = load_body_masses(
            session,
            _gm_table({999: (869.3, "gm_de440.tpc"), 507: (0.13, "Gravity.tpc")}),
            EntityStub({"Q1": entity}),
            _units(),
        )
        pluto = masses.pick("naif-999", 999, None, ObjectType.dwarf_planet)
        assert pluto == BodyMass(mass_kg_from_gm(869.3), "pck", False, "gm_de440.tpc")
        sinope = masses.pick("naif-509", 509, "Q1", ObjectType.moon)
        assert sinope == BodyMass(1.0e17, "wikidata")
        assert masses.pick("naif-507", 507, None, ObjectType.moon) == BodyMass(
            mass_kg_from_gm(0.13), "pck", True, "Gravity.tpc"
        )

    def test_the_table_takes_the_digits_of_gm_de440(self, session: Session):
        session.add(Object(id="naif-705", naif_id=705, object_type=ObjectType.moon))
        session.add(
            JPLSatellitePhysical(
                object_id="naif-705",
                naif_id=705,
                gm_km3_s2="4.3",
                gm_sigma_km3_s2=0.2,
                ephemeris="URA111",
            )
        )
        session.commit()
        masses = load_body_masses(
            session,
            _gm_table({705: (4.3195168992321005, "gm_de440.tpc")}),
            EntityStub({}),
            _units(),
        )
        assert masses.pick("naif-705", 705, None, ObjectType.moon) == BodyMass(
            mass_kg_from_gm(4.3195168992321005), "pck", False, "gm_de440.tpc"
        )


class TestMoonSatellites:
    def test_the_moons_of_each_body(self, session: Session):
        session.add(
            Object(
                id="spkid-20065803", naif_id=2065803, object_type=ObjectType.asteroid
            )
        )
        session.add(
            Object(
                id="spkid-120065803",
                naif_id=120065803,
                object_type=ObjectType.moon,
                parent_id="spkid-20065803",
                wikidata_qid="Q1",
            )
        )
        session.commit()
        assert moon_satellites(session) == {
            "spkid-20065803": (
                Satellite("spkid-120065803", 120065803, "Q1", ObjectType.moon),
            )
        }

    def test_a_body_without_moons_has_none(self):
        assert BodyMasses().satellites("spkid-20000433") == ()


class TestBundleFields:
    def test_a_measured_mass(self):
        assert bundle_fields(BodyMass(1.0, "sbdb")) == {
            "mass_kg": 1.0,
            "mass_source": "sbdb",
        }

    def test_a_nominal_mass_names_its_kernel(self):
        assert bundle_fields(BodyMass(1.0, "pck", True, "Gravity.tpc")) == {
            "mass_kg": 1.0,
            "mass_source": "pck",
            "mass_reference": "Gravity.tpc",
            "mass_nominal": True,
        }

    def test_a_mass_from_a_paper_names_the_paper(self):
        paper = {"title": "Pätzold et al. 2011", "url": "https://doi.org/p"}
        assert bundle_fields(BodyMass(1.7e18, "literature", reference=paper)) == {
            "mass_kg": 1.7e18,
            "mass_source": "literature",
            "mass_reference": paper,
        }

    def test_a_system_mass(self):
        assert bundle_fields(BodyMass(1.0, "astersat", system=True)) == {
            "mass_kg": 1.0,
            "mass_source": "astersat",
            "mass_system": True,
        }

    def test_no_mass_writes_nothing(self):
        assert bundle_fields(None) == {}
