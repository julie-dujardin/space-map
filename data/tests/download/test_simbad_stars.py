"""Tests for the SIMBAD star list and the Gaia rows of its named stars."""

import csv
import json
import re

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from space_map_data.download.downloader import DownloadError
from space_map_data.download.providers.exoplanets import tap
from space_map_data.download.providers.stars import (
    gaia_bulk,
    gaia_fidelity,
    gaia_named,
    gaia_source,
    iau_names,
    simbad_stars,
)
from space_map_data.download.providers.stars.gaia_named import (
    GaiaNamedStarsDownloader,
)
from space_map_data.download.providers.stars.simbad_stars import (
    SimbadStarsDownloader,
    iau_identifiers,
    simbad_bayer,
    star_types,
)

OTYPEDEF = (
    "otype,path,label\n"
    '"*","*","Star"\n'
    '"**","* > **","**"\n'
    '"Pl","* > Pl","Planet"\n'
    '"PN","* > Ev* > PN","PlanetaryNeb"\n'
    '"G","G","Galaxy"\n'
)
# The fake SIMBAD: oid → (main_id, otype, nbref, identifiers).
OBJECTS = {
    1: ("* alf Ori", "*", 900, ["* alf Ori", "HIP 27989", "Gaia DR3 11"]),
    2: ("HD 123", "*", 25, ["HD 123", "Gaia DR3 12"]),
    3: ("HD 456", "*", 3, ["HD 456"]),
    4: ("* kap CrA", "**", 4, ["* kap CrA"]),
    5: ("* kap01 CrA", "*", 15, ["* kap01 CrA"]),
    6: ("TYC 1-2-3", "*", 2, ["TYC 1-2-3"]),
    7: ("NAME Dilmun", "*", 8, ["NAME Dilmun", "Gaia DR3 17"]),
    8: ("HD 789", "*", 1, ["HD 789"]),
}
# (parent, child)
LINKS = [(4, 5), (4, 6), (1, 99)]


class FakeSimbad:
    """Answers the queries of the provider from OBJECTS and LINKS."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def rows(self, client, url, query, *, max_rows=None):
        self.queries.append(query)
        assert max_rows == simbad_stars.MAX_ROWS
        if "nbref >=" in query:
            found = [o for o, v in OBJECTS.items() if v[2] >= 20 and v[1] != "Pl"]
        else:
            match = re.search(r"like '([^%]*)%'", query)
            assert match is not None
            prefix = match[1]
            found = [
                o for o, v in OBJECTS.items() if any(i.startswith(prefix) for i in v[3])
            ]
        return ["oid"], [[str(o)] for o in found]

    def join(self, client, url, query, column, datatype, values, chunk):
        self.queries.append(query)
        if not values:
            raise DownloadError(f"No {column} to send to {url}")
        if "i.id = s.name" in query:
            found = []
            for value in values:
                for oid, (_, _, _, ids) in OBJECTS.items():
                    if value in ids:
                        found.append([value, str(oid)])
            return ["name", "oidref"], found
        if "h.parent = s.oid" in query:
            rows = [[str(p), str(c)] for p, c in LINKS if p in values and c in OBJECTS]
            return ["parent", "child"], rows
        if "h.child = s.oid" in query:
            rows = [[str(c), str(p)] for p, c in LINKS if c in values]
            return ["child", "parent"], rows
        if "from TAP_UPLOAD.sent as s join basic" in query:
            header = ["oid", "main_id", "otype", "nbref"]
            return header, [
                [str(v), OBJECTS[v][0], OBJECTS[v][1], str(OBJECTS[v][2])]
                for v in values
            ]
        if "allfluxes" in query:
            return ["oidref", "B", "V", "G"], [["1", "2.27", "0.42", ""]]
        assert "join ident" in query
        return ["oidref", "id"], [
            [str(v), i]
            for v in values
            for i in OBJECTS[v][3]
            if i.startswith(simbad_stars.IDENTIFIERS)
        ]


def _rows(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture
def fake(tmp_path, monkeypatch):
    names = tmp_path / "names.json"
    names.write_text(
        json.dumps(
            [
                {iau_names.NAME_COLUMN: "Betelgeuse", "HIP": "27989"},
                {
                    iau_names.NAME_COLUMN: "Dilmun",
                    "Designation": "WASP-121",
                    "Simbad spelling": "Dilmun",
                    "HIP": "",
                },
                {iau_names.NAME_COLUMN: "Hidden", "Designation": "HD 789", "HIP": ""},
                {iau_names.NAME_COLUMN: "Nowhere", "Designation": "-", "HIP": ""},
            ]
        )
    )
    monkeypatch.setattr(simbad_stars, "NAMES_FILE", names)
    monkeypatch.setattr(SimbadStarsDownloader, "inputs", (names,))
    monkeypatch.setattr(simbad_stars, "OUT_DIR", tmp_path / "simbad")
    monkeypatch.setattr(simbad_stars, "MIN_REFERENCES", 20)
    simbad = FakeSimbad()
    monkeypatch.setattr(simbad_stars, "tap_rows", simbad.rows)
    monkeypatch.setattr(simbad_stars, "tap_join", simbad.join)
    monkeypatch.setattr(simbad_stars, "tap_sync", lambda *a, **k: OTYPEDEF)
    return simbad


class TestSelection:
    """The star types and the identifiers of an IAU name."""

    def test_star_types_leave_out_planets_and_nebulae(self):
        assert star_types(OTYPEDEF) == ["*", "**"]

    def test_a_tree_without_stars_fails(self):
        with pytest.raises(DownloadError, match="no node"):
            star_types('otype,path\n"G","G"\n')

    def test_iau_identifiers_in_order(self):
        entry = {"Simbad spelling": "Dilmun", "Designation": "WASP-121", "HIP": "7"}
        assert iau_identifiers(entry) == ["NAME Dilmun", "WASP-121", "HIP 7"]
        assert iau_identifiers({"Designation": "-", "HIP": ""}) == []
        entry = {
            "Simbad spelling": "Siwarha",
            "Designation": "-",
            "Bayer ID": "α Ori B",
        }
        assert iau_identifiers(entry) == ["NAME Siwarha", "* alf Ori B"]

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("τ2 Aqr", "* tau02 Aqr"),
            ("ζ Psc B", "* zet Psc B"),
            ("µ Leo", "* mu. Leo"),
            ("88 Psc", "* 88 Psc"),
            ("HIP 91014", "HIP 91014"),
        ],
    )
    def test_bayer_ids_as_simbad_writes_them(self, text, expected):
        assert simbad_bayer(text) == expected


class TestSimbadStarsDownloader:
    """The list, its components and the files it writes."""

    def test_writes_the_list(self, fake):
        SimbadStarsDownloader(httpx.Client()).download()
        out = simbad_stars.OUT_DIR
        basic = [int(row["oid"]) for row in _rows(out / simbad_stars.BASIC_FILE)]
        # 1 and 2 by references, 1, 4, 5 and 7 by identifier, 8 by an IAU
        # name, 6 as a component of 4. 3 is not well known.
        assert basic == [1, 2, 4, 5, 6, 7, 8]
        ident = _rows(out / simbad_stars.IDENT_FILE)
        assert {"oidref": "1", "id": "Gaia DR3 11"} in ident
        assert all(row["id"] != "TYC 1-2-3" for row in ident)
        links = _rows(out / simbad_stars.LINKS_FILE)
        assert {(row["child"], row["parent"]) for row in links} == {
            ("5", "4"),
            ("6", "4"),
        }
        assert _rows(out / simbad_stars.IAU_FILE) == [
            {"name": "Betelgeuse", "identifier": "HIP 27989", "oid": "1"},
            {"name": "Dilmun", "identifier": "NAME Dilmun", "oid": "7"},
            {"name": "Hidden", "identifier": "HD 789", "oid": "8"},
            {"name": "Nowhere", "identifier": "", "oid": ""},
        ]
        meta = json.loads((out / "metadata.json").read_text())
        assert meta["complete"] and meta["record_count"] == 7
        assert (meta["counts"]["iau"], meta["counts"]["components"]) == (1, 1)
        assert meta["iau_resolved"] == 3

    def test_a_cluster_gives_no_components(self, fake, monkeypatch):
        monkeypatch.setattr(simbad_stars, "MAX_CHILDREN", 1)
        SimbadStarsDownloader(httpx.Client()).download()
        basic = _rows(simbad_stars.OUT_DIR / simbad_stars.BASIC_FILE)
        assert "6" not in {row["oid"] for row in basic}

    def test_a_level_that_adds_nothing_ends_the_walk(self, fake, monkeypatch):
        monkeypatch.setattr(simbad_stars, "MAX_CHILDREN", 1)
        SimbadStarsDownloader(httpx.Client()).download()
        assert sum("h.parent = s.oid" in query for query in fake.queries) == 1

    def test_missing_names_fail(self, fake):
        simbad_stars.NAMES_FILE.unlink()
        with pytest.raises(DownloadError, match="run its provider first"):
            SimbadStarsDownloader(httpx.Client()).download()


class TestTapRowLimit:
    """A query with a row limit sends it and refuses a full answer."""

    def test_limit_is_sent_and_a_full_answer_fails(self):
        sent = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(request.content)
            return httpx.Response(200, text="oid\n1\n2\n")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert tap.tap_rows(client, "https://tap", "q", max_rows=3)[1] == [
            ["1"],
            ["2"],
        ]
        assert b"MAXREC=3" in sent[0]
        with pytest.raises(DownloadError, match="reached 2 rows"):
            tap.tap_rows(client, "https://tap", "q", max_rows=2)


GAIA_COLUMNS = [
    {"name": name, "datatype": "float64"} for name in gaia_source.COLUMNS
] + [{"name": "source_id", "datatype": "int64"}]
# The archive's rows without a 5σ parallax, by source_id.
ARCHIVE = {11: "1.5", 17: ""}
FIDELITY = {11: "0.2,-1.0"}


class TestGaiaNamedStarsDownloader:
    """The Gaia rows of the listed stars that gaia_source leaves out."""

    @pytest.fixture
    def downloader(self, tmp_path, monkeypatch):
        ident = tmp_path / "ident.csv"
        ident.write_text(
            "oidref,id\n1,Gaia DR3 11\n2,Gaia DR3 12\n7,Gaia DR3 17\n1,HIP 27989\n"
        )
        columns = tmp_path / "columns.json"
        # source_id comes last so that its own type wins.
        declared = {c["name"]: c for c in GAIA_COLUMNS}
        for name in ("phot_variable_flag", "libname_gspphot"):
            declared[name] = {"name": name, "datatype": "string"}
        columns.write_text(json.dumps(list(declared.values())))
        monkeypatch.setattr(gaia_named, "IDENT_FILE", ident)
        monkeypatch.setattr(gaia_named, "COLUMNS_FILE", columns)
        monkeypatch.setattr(GaiaNamedStarsDownloader, "inputs", (ident, columns))
        monkeypatch.setattr(gaia_named, "OUT_DIR", tmp_path / "named")
        monkeypatch.setattr(gaia_bulk, "OUT_DIR", tmp_path)
        self.asked: list[list[int]] = []
        self.cut = False

        def handler(request: httpx.Request) -> httpx.Response:
            body = request.content
            ids = [int(i) for i in re.findall(rb"<TD>(\d+)</TD>", body)]
            self.asked.append(ids)
            if b"gaiaedr3_spurious" in body:
                rows = [f"{i},{FIDELITY[i]}" for i in ids if i in FIDELITY]
                text = "source_id,fidelity_v2,norm_dg\n" + "".join(
                    f"{row}\n" for row in rows
                )
                return httpx.Response(200, text=text)
            assert b"parallax_over_error is null" in body
            found = [i for i in ids if i in ARCHIVE]
            if self.cut:
                self.cut, found = False, found[:1]
            header = ",".join(gaia_source.COLUMNS)
            lines = []
            for i in found:
                values = {name: "" for name in gaia_source.COLUMNS}
                values |= {"source_id": str(i), "parallax": ARCHIVE[i]}
                lines.append(",".join(values[name] for name in gaia_source.COLUMNS))
            return httpx.Response(200, text="\n".join([header, *lines]) + "\n")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        return GaiaNamedStarsDownloader(client)

    def test_writes_the_rows_and_their_fidelity(self, downloader):
        downloader.download()
        rows = pq.read_table(gaia_named.OUT_DIR / gaia_named.SOURCE_FILE)
        assert rows["source_id"].to_pylist() == [11, 17]
        assert rows["parallax"].to_pylist() == [1.5, None]
        assert rows.schema.field("source_id").type == pa.int64()
        assert rows.schema.field("libname_gspphot").type == pa.string()
        fidelity = pq.read_table(gaia_named.OUT_DIR / gaia_named.FIDELITY_FILE)
        assert fidelity.to_pydict() == {
            "source_id": [11],
            "fidelity_v2": pytest.approx([0.2]),
            "norm_dg": pytest.approx([-1.0]),
        }
        meta = json.loads(downloader.metadata_file.read_text())
        assert (meta["record_count"], meta["ids_sent"]) == (2, 3)
        # A complete answer is not asked again.
        assert self.asked == [[11, 12, 17], [11, 17]]

    def test_a_cut_answer_is_completed(self, downloader, monkeypatch):
        # One row is an answer at the row limit.
        monkeypatch.setattr(gaia_fidelity, "DEFAULT_ROWS", 1)
        self.cut = True
        downloader.download()
        rows = pq.read_table(gaia_named.OUT_DIR / gaia_named.SOURCE_FILE)
        assert sorted(rows["source_id"].to_pylist()) == [11, 17]
        assert self.asked[:3] == [[11, 12, 17], [12, 17], [12]]
