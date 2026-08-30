"""Parsing the Deep Space Catalog.

GCAT states precision by truncating a date and by writing a trailing `?`, so
both have to survive parsing — a phase start known only to the month is
rejected downstream and would otherwise be indistinguishable from one known to
the minute.
"""

import datetime
import math

from space_map_data.probes.deepcat import (
    DatePrecision,
    parse_gcat_date,
    parse_objects,
    parse_phases,
    parse_solar_elements,
)


class TestDateParsing:
    """Every truncation GCAT writes, and the uncertainty flag on each."""

    def test_full_precision_to_the_minute(self):
        d = parse_gcat_date("1962 Dec 12 1745")
        assert d is not None
        assert d.precision is DatePrecision.MINUTE
        assert not d.uncertain
        midnight = datetime.date(1962, 12, 12).toordinal() + 1721424.5
        assert math.isclose(d.jd, midnight + (17 * 3600 + 45 * 60) / 86400.0)

    def test_seconds_are_kept(self):
        d = parse_gcat_date("2018 May 5 1105:30")
        assert d is not None
        assert d.precision is DatePrecision.SECOND

    def test_day_precision_centres_on_midday(self):
        d = parse_gcat_date("1961 May 20")
        assert d is not None
        assert d.precision is DatePrecision.DAY
        assert d.jd % 1 == 0.0

    def test_month_and_year_truncations(self):
        month, year = parse_gcat_date("1961 Mar"), parse_gcat_date("1962")
        assert month is not None and year is not None
        assert month.precision is DatePrecision.MONTH
        assert year.precision is DatePrecision.YEAR

    def test_decade_is_the_coarsest_form(self):
        d = parse_gcat_date("1970s?")
        assert d is not None
        assert d.precision is DatePrecision.DECADE
        assert d.uncertain

    def test_question_mark_doubles_the_admitted_interval(self):
        certain = parse_gcat_date("1961 May 20")
        doubted = parse_gcat_date("1961 May 20?")
        assert certain is not None and doubted is not None
        assert doubted.uncertain
        assert doubted.half_width_d == 2 * certain.half_width_d

    def test_blank_and_dash_carry_no_date(self):
        assert parse_gcat_date("") is None
        assert parse_gcat_date("-") is None

    def test_coarser_forms_admit_wider_intervals(self):
        dates = [
            parse_gcat_date(raw)
            for raw in ("1962 Dec 12 1745", "1962 Dec 12", "1962 Dec", "1962")
        ]
        assert all(d is not None for d in dates)
        widths = [d.half_width_d for d in dates if d is not None]
        assert widths == sorted(widths)


class TestSolarElements:
    """The `peri x apo AU x inc` field, and what it derives."""

    def test_plain_figures(self):
        e = parse_solar_elements("   0.718  x    1.019  AU x   0.58")
        assert e is not None
        assert (e.peri_au, e.apo_au, e.inc_deg) == (0.718, 1.019, 0.58)
        assert not e.uncertain

    def test_a_question_mark_on_any_figure_marks_the_set_uncertain(self):
        for raw in ("0.980? x 1.315 AU x 0.04", "0.980 x 1.315 AU x 0.04?"):
            elements = parse_solar_elements(raw)
            assert elements is not None and elements.uncertain

    def test_semi_major_and_eccentricity_follow_from_the_apsides(self):
        e = parse_solar_elements("1.000 x 3.000 AU x 0.00")
        assert e is not None
        assert math.isclose(e.semi_major_au, 2.0)
        assert math.isclose(e.eccentricity, 0.5)

    def test_an_absent_orbit_is_not_an_error(self):
        assert parse_solar_elements("") is None
        assert parse_solar_elements("unknown") is None


class TestTables:
    """Row parsing, including the trailing columns GCAT drops."""

    OBJECTS = (
        "#DeepID\tStdID\tIntDes\tLDate\tName\tAltName\n"
        "D00088\tS01730\t1965 091A\t1965 Nov 12\tVenera-2\tAMS Venera\n"
        "D00001\tA00016\t1959 MU\t1959 Jan 2\tVostok Stage 3\t\n"
    )

    def test_catalogue_number_recovered_only_from_agency_ids(self):
        objects = parse_objects(self.OBJECTS)
        assert objects["D00088"].norad_id == 1730
        # `A`-prefixed ids are GCAT's own analyst numbers and join to nothing.
        assert objects["D00001"].norad_id is None

    def test_phase_row_with_dropped_trailing_columns(self):
        phases = parse_phases(
            "#DeepID\tName\tPhase\tBody\tPStart\tPEnd\tDest\tEpoch\tOrbit\n"
            "D00088\tVenera-2\t  0 \tEarth\t1965 Nov 12 0500\t\tLaunch\n"
        )
        assert len(phases) == 1
        assert phases[0].elements is None
        assert phases[0].is_open_ended

    def test_arrival_body_read_from_the_destination_wording(self):
        phases = parse_phases(
            "#DeepID\tName\tPhase\tBody\tPStart\tPEnd\tDest\tEpoch\tOrbit\n"
            "D00088\tVenera-2\t  4 \tSun\t1965 Nov 13\t1966 Feb 26\t"
            "Entered Venus sphere\t1965 Nov\t0.718 x 1.019 AU x 0.58\n"
            "D00088\tVenera-2\t  7 \tSun\t1966 Feb 28\t-\t"
            "In solar orbit\t1966 Mar\t0.718 x 1.019 AU x 0.58\n"
        )
        assert phases[0].arrival_body == "Venus"
        assert not phases[0].is_open_ended
        assert phases[1].arrival_body is None
        assert phases[1].is_open_ended
