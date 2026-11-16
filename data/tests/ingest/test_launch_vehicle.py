from space_map_data.ingest.providers.objects.launch_vehicle import (
    LaunchVehicleIngestor,
)

# GCAT's lv.tsv as published since November 2026, with its GenericName column.
_LV_TSV = (
    "#LV_Name\tLV_Family\tLV_Manufacturer\tLV_Variant\tLV_Alias\tLV_Min_Stage\t"
    "LV_Max_Stage\tLength\tLFlag\tDiameter\tDFlag\tLaunch_Mass\tMFlag\t"
    "LEO_Capacity\tGTO_Capacity\tTO_Thrust\tClass\tApogee\tRange\tGenericName\n"
    "# Updated 2026 Nov  9 0051:47\n"
    "Falcon 9\tFalcon9             \tSPX\t-\t-\t  1\t2\t 54.9 \t \t 3.65 \t \t"
    "   333.4 \t \t    9300 \t    3400 \t    4940 \tO\t   200 \t-\tFalcon 9\n"
    "Falcon 9\tFalcon9             \tSPX\tFT5\t-\t  1\t2\t 68.4 \t \t 3.65 \t \t"
    "   480.0 \t \t   13150 \t    4850 \t    5886 \tO\t   200 \t-\tFalcon 9\n"
)


class TestParseRows:
    """lv.tsv rows parse into one launch vehicle per name."""

    def test_a_current_row_parses(self, tmp_path):
        path = tmp_path / "lv.tsv"
        path.write_text(_LV_TSV)
        ingestor = LaunchVehicleIngestor.__new__(LaunchVehicleIngestor)
        ingestor.path = path
        ingestor.malformed = 0
        ingestor.unparsed_numbers = 0

        rows = ingestor._parse_rows()

        assert ingestor.malformed == 0
        assert len(rows) == 1
        assert rows[0]["lv_name"] == "Falcon 9"
        assert rows[0]["family"] == "Falcon9"
        assert rows[0]["length_m"] == 54.9
