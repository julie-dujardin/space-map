"""Tests for space_map_data.export.objects.body_radius."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from space_map_data.constants.body_literature import VOLUMES
from space_map_data.export.objects.body_radius import (
    BodyRadii,
    BodyRadius,
    bundle_fields,
    catalogue_sizes,
    is_placeholder_kernel,
    kernel_shapes,
    lineup_radii,
    literature_shapes,
    load_body_radii,
    placeholder_shapes,
)
from space_map_data.export.wikidata import WikidataEntity
from space_map_data.models.object import (
    AsterSatMoon,
    JohnstonMoon,
    JohnstonSystem,
    Object,
    ObjectType,
    SsODNet,
)
from space_map_data.models.object.sbdb import SBDB, OrbitClass
from tests.conftest import EntityStub

_PLUTO = {"a": 1188.3, "b": 1188.3, "c": 1188.3}
# Varuna, a light-curve ellipsoid that no kernel holds.
_VARUNA_NAIF = 2020000
_VARUNA = {"a": 500.0, "b": 330.0, "c": 300.0}
# Kerberos in the New Horizons catch-all kernel: a synthetic 100 km sphere.
_SYNTHETIC = {"a": 100.0, "b": 100.0, "c": 100.0}
_NH_CATCH_ALL = "nh_stars_kbo_centaur_v005.tpc"


def _sphere(radius_km: float, source: str, nominal: bool = False) -> BodyRadius:
    return BodyRadius(radius_km, radius_km, radius_km, source, nominal=nominal)


def _resolver(**kwargs) -> BodyRadii:
    return BodyRadii(
        kwargs.get("shapes", {}),
        kwargs.get("sizes", {}),
        lambda qid: kwargs.get("wikidata", {}).get(qid),
        kwargs.get("nominal_sizes", {}),
        kwargs.get("placeholders", {}),
        kwargs.get("volumes", {}),
    )


class TestPick:
    """A kernel shape, the catalogue sizes, Wikidata, then the nominal sizes."""

    def test_kernel_shape_wins(self):
        radii = _resolver(
            shapes=kernel_shapes({999: _PLUTO}),
            sizes={"naif-999": _sphere(1000.0, "johnston")},
            wikidata={"Q339": 1100.0},
        )
        size = radii.pick("naif-999", 999, "Q339", ObjectType.dwarf_planet)
        assert size is not None
        assert (size.axes(), size.source) == (_PLUTO, "pck")

    def test_catalogue_size_beats_wikidata(self):
        radii = _resolver(
            sizes={"spkid-120050000": _sphere(40.5, "astersat")},
            wikidata={"Q83894": 100.0},
        )
        size = radii.pick("spkid-120050000", None, "Q83894", ObjectType.moon)
        assert size == _sphere(40.5, "astersat")

    def test_wikidata_is_the_last_fallback(self):
        radii = _resolver(wikidata={"Q18481": 36.0})
        size = radii.pick("naif-716", 716, "Q18481", ObjectType.moon)
        assert size == _sphere(36.0, "wikidata")

    def test_wikidata_beats_a_nominal_catalogue_size(self):
        radii = _resolver(
            nominal_sizes={"spkid-20508788": _sphere(89.5, "johnston", nominal=True)},
            wikidata={"Q1": 80.0},
        )
        size = radii.pick("spkid-20508788", None, "Q1", ObjectType.asteroid_tno)
        assert size == _sphere(80.0, "wikidata")

    def test_a_nominal_catalogue_size_beats_a_placeholder(self):
        radii = _resolver(
            nominal_sizes={"naif-904": _sphere(9.0, "johnston", nominal=True)},
            placeholders=placeholder_shapes({904: _SYNTHETIC}, {904: _NH_CATCH_ALL}),
        )
        size = radii.pick("naif-904", 904, None, ObjectType.moon)
        assert size == _sphere(9.0, "johnston", nominal=True)

    def test_a_placeholder_is_the_last_fallback(self):
        radii = _resolver(
            placeholders=placeholder_shapes({904: _SYNTHETIC}, {904: _NH_CATCH_ALL})
        )
        size = radii.pick("naif-904", 904, None, ObjectType.moon)
        assert size == _sphere(100.0, "pck", nominal=True)

    def test_no_source_gives_none(self):
        assert _resolver().pick("naif-716", 716, "Q18481", ObjectType.moon) is None

    def test_an_empty_resolver_reads_no_wikidata(self):
        assert BodyRadii().pick("naif-716", 716, "Q18481", ObjectType.moon) is None

    def test_of_reads_the_object_ids(self):
        radii = _resolver(wikidata={"Q18481": 36.0})
        obj = Object(
            id="naif-716", naif_id=716, wikidata_qid="Q18481", object_type="moon"
        )
        assert radii.of(obj) == _sphere(36.0, "wikidata")

    def test_a_craft_takes_no_wikidata_size(self):
        radii = _resolver(wikidata={"Q26540": 54.0})
        iss = Object(
            id="norad_satcat-25544",
            wikidata_qid="Q26540",
            object_type=ObjectType.spacecraft,
        )
        assert radii.of(iss) is None

    @pytest.mark.parametrize(
        "object_type",
        [ObjectType.spacecraft, ObjectType.debris, ObjectType.undocumented],
    )
    def test_a_craft_never_gets_a_size(self, object_type):
        radii = _resolver(
            shapes=kernel_shapes({-170: _PLUTO}),
            sizes={"probe-170": _sphere(1.0, "johnston")},
            wikidata={"Q186447": 0.00325},
        )
        assert radii.pick("probe-170", -170, "Q186447", object_type) is None


class TestKernelShapes:
    """Each ellipsoid of `load_radii` names the table it came from."""

    def test_a_placeholder_kernel_is_left_out(self):
        assert kernel_shapes({904: _SYNTHETIC}, {904: _NH_CATCH_ALL}) == {}

    def test_a_placeholder_is_nominal(self):
        shapes = placeholder_shapes({904: _SYNTHETIC}, {904: _NH_CATCH_ALL})
        assert shapes == {904: _sphere(100.0, "pck", nominal=True)}

    def test_a_measured_kernel_has_no_placeholder(self):
        assert placeholder_shapes({999: _PLUTO}, {999: "pck00011.tpc"}) == {}

    @pytest.mark.parametrize(
        ("kernel", "placeholder"),
        [
            ("juice_jup015.tpc", True),
            ("cpck_rock_21Jan2011_merged.tpc", True),
            ("nh_stars_kbo_centaur_v005.tpc", True),
            ("cpck01Dec2012.tpc", False),
            ("pck00011.tpc", False),
            ("", False),
            (None, False),
        ],
    )
    def test_the_placeholder_kernels(self, kernel, placeholder):
        assert is_placeholder_kernel(kernel) is placeholder

    def test_a_kernel_body_is_pck_with_no_reference(self):
        assert kernel_shapes({999: _PLUTO})[999] == BodyRadius(
            1188.3, 1188.3, 1188.3, "pck"
        )

    def test_a_measured_shape_cites_its_work(self):
        shape = kernel_shapes({_VARUNA_NAIF: _VARUNA})[_VARUNA_NAIF]
        assert shape.source == "photometry"
        assert shape.reference is not None and shape.reference["url"]


class TestLiteratureShapes:
    """A size from a paper cites the paper."""

    def test_kerberos_is_the_new_horizons_ellipsoid(self):
        kerberos = literature_shapes()[904]
        assert kerberos.axes() == {"a": 9.5, "b": 5.0, "c": 4.5}
        assert kerberos.source == "literature"
        assert kerberos.reference is not None
        assert kerberos.reference["url"] == "https://doi.org/10.1126/science.aae0030"

    def test_himalia_is_the_neowise_diameter(self):
        assert literature_shapes()[506].mean_km == pytest.approx(69.8)

    def test_a_paper_beats_the_kernel(self):
        radii = _resolver(
            shapes={
                **kernel_shapes({506: {"a": 85.0, "b": 85.0, "c": 85.0}}),
                **literature_shapes(),
            }
        )
        size = radii.pick("naif-506", 506, None, ObjectType.moon)
        assert size is not None and size.source == "literature"


class TestShapeModelVolumes:
    """A body with a paper's shape model carries its volume."""

    def test_phobos_carries_willner_2014(self):
        radii = _resolver(
            shapes=kernel_shapes({401: {"a": 13.0, "b": 11.4, "c": 9.1}}),
            volumes=VOLUMES,
        )
        size = radii.pick("naif-401", 401, None, ObjectType.moon)
        assert size is not None
        assert size.volume_km3 == 5742
        assert size.volume_reference is not None
        assert (
            size.volume_reference["url"] == "https://doi.org/10.1016/j.pss.2013.12.006"
        )

    def test_the_volume_of_an_equal_volume_radius(self):
        """Atlas: Buratti et al. 2019 give Rm = 14.9 km."""
        radii = _resolver(
            sizes={"naif-615": _sphere(15.0, "wikidata")}, volumes=VOLUMES
        )
        size = radii.pick("naif-615", 615, None, ObjectType.moon)
        assert size is not None
        assert size.volume_km3 == pytest.approx(13856.3)

    def test_a_body_with_no_size_takes_no_volume(self):
        radii = _resolver(volumes=VOLUMES)
        assert radii.pick("naif-401", 401, None, ObjectType.moon) is None

    def test_a_body_with_no_shape_model_has_no_volume(self):
        radii = _resolver(shapes=kernel_shapes({999: _PLUTO}), volumes=VOLUMES)
        size = radii.pick("naif-999", 999, None, ObjectType.dwarf_planet)
        assert size is not None and size.volume_km3 is None


def _sizes(session: Session) -> dict[str, BodyRadius]:
    return catalogue_sizes(session)[0]


class TestCatalogueSizes:
    """SsODNet, SBDB, then the moon catalogues, from the ingested tables."""

    @staticmethod
    def _body(session: Session, object_id: str, object_type=ObjectType.moon):
        session.add(Object(id=object_id, object_type=object_type))

    @staticmethod
    def _astersat(object_id: str, parent: str, radius_km: float) -> AsterSatMoon:
        return AsterSatMoon(
            object_id=object_id,
            parent_object_id=parent,
            astersat_id="AN050000Quaoar",
            system_label="(50000) Quaoar",
            satellite_label="Weywot",
            frame="geoequat J2000",
            epoch_mjd=52000.0,
            a_km=13289.0,
            e=0.0,
            i=0.0,
            om=0.0,
            w=0.0,
            ma=0.0,
            n=0.0,
            per_d=12.43,
            satellite_radius_km=radius_km,
        )

    def test_astersat_beats_johnston(self, session: Session):
        """Weywot: AsterSat 40.5 km, Johnston a 200 km diameter."""
        self._body(session, "spkid-20050000", ObjectType.dwarf_planet)
        self._body(session, "spkid-120050000")
        session.add(
            JohnstonSystem(
                object_id="spkid-20050000", page="am-50000", designation="Quaoar"
            )
        )
        session.add(
            JohnstonMoon(
                object_id="spkid-120050000",
                parent_object_id="spkid-20050000",
                label="Weywot",
                diameter_km=200.0,
            )
        )
        session.add(self._astersat("spkid-120050000", "spkid-20050000", 40.5))
        session.commit()
        sizes = _sizes(session)
        assert sizes["spkid-120050000"] == _sphere(40.5, "astersat")

    def test_astersat_sizes_the_primary_too(self, session: Session):
        """1998 WW31: only its moon's AsterSat row gives the primary a size."""
        self._body(session, "spkid-50031846", ObjectType.asteroid_tno)
        self._body(session, "spkid-150031846")
        moon = self._astersat("spkid-150031846", "spkid-50031846", 61.5)
        moon.primary_radius_km = 74.0
        session.add(moon)
        session.commit()
        sizes = _sizes(session)
        assert sizes["spkid-50031846"] == _sphere(74.0, "astersat")
        assert sizes["spkid-150031846"] == _sphere(61.5, "astersat")

    def test_johnston_beats_astersat_for_a_primary(self, session: Session):
        self._body(session, "spkid-20136199", ObjectType.dwarf_planet)
        self._body(session, "spkid-120136199")
        session.add(
            JohnstonSystem(
                object_id="spkid-20136199",
                page="am-136199",
                designation="Eris",
                primary_diameter_km=2326.0,
            )
        )
        moon = self._astersat("spkid-120136199", "spkid-20136199", 350.0)
        moon.primary_radius_km = 1200.0
        session.add(moon)
        session.commit()
        assert _sizes(session)["spkid-20136199"] == _sphere(1163.0, "johnston")

    def test_johnston_diameters_are_halved(self, session: Session):
        """Eris's primary and a companion with no AsterSat fit."""
        self._body(session, "spkid-20136199", ObjectType.dwarf_planet)
        self._body(session, "spkid-120136199")
        session.add(
            JohnstonSystem(
                object_id="spkid-20136199",
                page="am-136199",
                designation="Eris",
                diameter_km=2429.0,
                primary_diameter_km=2326.0,
            )
        )
        session.add(
            JohnstonMoon(
                object_id="spkid-120136199",
                parent_object_id="spkid-20136199",
                label="Dysnomia",
                diameter_km=700.0,
            )
        )
        session.commit()
        sizes = _sizes(session)
        assert sizes["spkid-20136199"] == _sphere(1163.0, "johnston")
        assert sizes["spkid-120136199"] == _sphere(350.0, "johnston")

    def test_sbdb_beats_johnston(self, session: Session):
        """Typhon: SBDB 192 km, Johnston's primary 162 km."""
        self._body(session, "spkid-20042355", ObjectType.asteroid_tno)
        session.add(
            SBDB(
                spkid="20042355",
                object_id="spkid-20042355",
                class_=OrbitClass.TNO,
                diameter=192.0,
            )
        )
        session.add(
            JohnstonSystem(
                object_id="spkid-20042355",
                page="am-42355",
                designation="Typhon",
                primary_diameter_km=162.0,
            )
        )
        session.commit()
        assert _sizes(session)["spkid-20042355"] == _sphere(96.0, "sbdb")

    def test_a_row_with_no_size_is_skipped(self, session: Session):
        self._body(session, "spkid-20042355", ObjectType.asteroid_tno)
        session.add(
            SBDB(spkid="20042355", object_id="spkid-20042355", class_=OrbitClass.TNO)
        )
        session.commit()
        assert catalogue_sizes(session) == ({}, {})

    def test_ssodnet_beats_sbdb(self, session: Session):
        """Gonggong: SsODNet 1239.5 km, SBDB 1535 km."""
        self._body(session, "spkid-20225088", ObjectType.dwarf_planet)
        session.add(
            SBDB(
                spkid="20225088",
                object_id="spkid-20225088",
                class_=OrbitClass.TNO,
                diameter=1535.0,
            )
        )
        session.add(SsODNet(object_id="spkid-20225088", diameter_km=1239.5))
        session.commit()
        assert _sizes(session)["spkid-20225088"] == _sphere(619.75, "ssodnet")

    def test_an_estimated_johnston_diameter_is_nominal(self, session: Session):
        """2000 CQ114: the archive estimates its primary from an albedo."""
        self._body(session, "spkid-20508788", ObjectType.asteroid_tno)
        session.add(
            JohnstonSystem(
                object_id="spkid-20508788",
                page="am-508788",
                designation="2000 CQ114",
                primary_diameter_km=179.0,
                primary_diameter_km_nominal=True,
            )
        )
        session.commit()
        sizes, nominal = catalogue_sizes(session)
        assert sizes == {}
        assert nominal["spkid-20508788"] == _sphere(89.5, "johnston", nominal=True)


class TestBundleFields:
    """The object bundle writes the pick into `radii`, with its source."""

    def test_pck_names_no_reference(self):
        assert bundle_fields(BodyRadius(1.0, 2.0, 3.0, "pck")) == {
            "radii": {"a": 1.0, "b": 2.0, "c": 3.0},
            "radii_source": "pck",
        }

    def test_a_measured_shape_carries_its_reference(self):
        ref = {"title": "Paper", "url": "https://doi.org/x"}
        fields = bundle_fields(BodyRadius(1.0, 2.0, 3.0, "occultation", ref))
        assert fields["radii_reference"] == ref

    def test_a_catalogue_sphere_names_its_catalogue(self):
        assert bundle_fields(_sphere(40.5, "astersat")) == {
            "radii": {"a": 40.5, "b": 40.5, "c": 40.5},
            "radii_source": "astersat",
        }

    def test_a_nominal_size_says_so(self):
        fields = bundle_fields(_sphere(100.0, "pck", nominal=True))
        assert fields["radii_nominal"] is True

    @pytest.mark.parametrize("size", [None, _sphere(96.0, "sbdb")])
    def test_sbdb_or_nothing_writes_nothing(self, size):
        assert bundle_fields(size) == {}


class TestLineupRadii:
    """A lineup record carries the pick as `radii`, with `source` unless PCK."""

    def test_pck_has_no_source(self):
        assert lineup_radii(BodyRadius(1.0, 1.0, 1.0, "pck")) == {
            "a": 1.0,
            "b": 1.0,
            "c": 1.0,
        }

    def test_a_wikidata_sphere_names_wikidata(self):
        assert lineup_radii(_sphere(36.0, "wikidata")) == {
            "a": 36.0,
            "b": 36.0,
            "c": 36.0,
            "source": "wikidata",
        }

    def test_a_placeholder_names_its_source_and_says_nominal(self):
        assert lineup_radii(_sphere(100.0, "pck", nominal=True)) == {
            "a": 100.0,
            "b": 100.0,
            "c": 100.0,
            "source": "pck",
            "nominal": True,
        }

    def test_a_ssodnet_sphere_names_ssodnet(self):
        """As the bundle's `radii_source`, so the footer can credit it."""
        assert lineup_radii(_sphere(469.7, "ssodnet")) == {
            "a": 469.7,
            "b": 469.7,
            "c": 469.7,
            "source": "ssodnet",
        }

    def test_sbdb_rides_in_diameter_km(self):
        assert lineup_radii(_sphere(96.0, "sbdb")) is None


class TestLoadBodyRadii:
    """The Wikidata fallback reads the radius claim, else the diameter claim."""

    @staticmethod
    def _quantity(pid: str, amount: str) -> dict:
        # Q828224 is the kilometre.
        value = {"amount": amount, "unit": "http://www.wikidata.org/entity/Q828224"}
        snak = {
            "snaktype": "value",
            "datavalue": {"value": value, "type": "quantity"},
        }
        return {pid: [{"mainsnak": snak, "rank": "normal", "type": "statement"}]}

    def _radii(self, session: Session, claims: dict) -> BodyRadii:
        entity = WikidataEntity(
            labels={}, descriptions={}, aliases={}, claims=claims, sitelinks={}
        )
        # Kilometres to metres, as the converter does for Q828224.
        units = MagicMock()
        units.convert_to_base.side_effect = lambda value, unit, expected_type: (
            value * 1000
        )
        return load_body_radii(session, {}, {}, EntityStub({"Q15610": entity}), units)

    def test_the_radius_claim(self, session: Session):
        radii = self._radii(session, self._quantity("P2120", "+500"))
        assert radii.pick(
            "spkid-20090377", None, "Q15610", ObjectType.dwarf_planet
        ) == _sphere(500.0, "wikidata")

    def test_half_the_diameter_claim_without_a_radius(self, session: Session):
        """Sedna has a Wikidata diameter and no other size."""
        radii = self._radii(session, self._quantity("P2386", "+995"))
        assert radii.pick(
            "spkid-20090377", None, "Q15610", ObjectType.dwarf_planet
        ) == _sphere(497.5, "wikidata")
