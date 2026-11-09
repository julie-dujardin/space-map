"""The citations of the orbits and held stars that the System tiles serve."""

import pytest

from space_map_data.constants.stars import binaries, literature
from space_map_data.export.extrasolar import citations
from space_map_data.export.extrasolar.citations import cite

ADS = citations.ADS_URL
GAIA = citations.GAIA_ORBITS_PAPER


class TestPapers:
    def test_every_binary_cites_a_known_paper(self):
        for binary in binaries.BINARIES.values():
            assert binary.reference in citations.PAPERS

    def test_every_literature_value_cites_a_known_paper(self):
        tables = (
            literature.DISTANCES,
            literature.RADII,
            literature.TEFFS,
            literature.LOGGS,
            literature.MASSES,
        )
        for value in (value for table in tables for value in table.values()):
            assert value.reference in citations.PAPERS

    def test_the_paper_tables_share_no_key(self):
        assert not set(literature.REFERENCES) & set(binaries.REFERENCES)

    def test_a_paper_key(self):
        assert cite({"source": "literature", "reference": "doyle_2011"}) == {
            "source": "literature",
            "reference": "doyle_2011",
            "short": "Doyle et al. 2011",
            "title": "Kepler-16: A Transiting Circumbinary Planet (Science 333, 1602)",
            "url": "https://doi.org/10.1126/science.1210923",
        }

    def test_an_unknown_key_has_no_work(self):
        found = cite({"source": "literature", "reference": "nobody_1900"})
        assert found["reference"] == "nobody_1900"
        assert (found["short"], found["title"], found["url"]) == (None, None, None)


class TestCatalogues:
    @pytest.mark.parametrize(
        ("source", "reference", "url"),
        [
            ("sbx", "2002AJ....124.1144L", ADS + "2002AJ....124.1144L"),
            ("sbx", "2021A&A...653A..49B", ADS + "2021A%26A...653A..49B"),
            ("msc", "SB9_2192 2002AJ....124.1144L", ADS + "2002AJ....124.1144L"),
            ("msc", "2021A&A...653A..49B 12.68y", ADS + "2021A%26A...653A..49B"),
            ("msc", "2026arXiv260329274K", ADS + "2026arXiv260329274K"),
            # Cut short in the MSC: no bibcode.
            ("msc", "2018A&A...619..32B = Del1999", None),
            ("msc", "VB6_Msn2023  I_1477 Gr.2", None),
            ("msc", "Tok 2025, prelim.", None),
            ("orb6", "Msn2023", None),
            ("sbx", None, None),
        ],
    )
    def test_a_bibcode_links_to_ads(self, source, reference, url):
        found = cite({"source": source, "reference": reference})
        assert found["url"] == url
        assert found["short"] is None and found["title"] is None

    @pytest.mark.parametrize(
        ("source", "reference"),
        [
            ("gaia-dr3-orbits", "4338096422163308546"),
            ("msc", "NSS SB1"),
            ("msc", "DR3 AORB syspect"),
        ],
    )
    def test_the_gaia_orbits(self, source, reference):
        found = cite({"source": source, "reference": reference})
        assert (found["short"], found["title"], found["url"]) == tuple(GAIA)
        assert found["reference"] == reference
