"""GCAT's size columns say "unknown" with a zero, not with a blank.

Nothing catalogued masses nothing or spans nothing, so a zero that survives
ingest reads downstream as a measurement and is quoted as one.
"""

from pathlib import Path

from space_map_data.ingest.providers.objects.gcat_satcat import load_gcat_hardware

_HEADER = (
    "#JCAT\tSatcat\tOwner\tState\tManufacturer\tBus\tMass\tMassFlag\tDryMass\t"
    "DryFlag\tLength\tLFlag\tDiameter\tDFlag\tSpan\tSpanFlag\n"
)


def _write_satcat(tmp_path: Path, *rows: str) -> Path:
    gcat_dir = tmp_path / "sources" / "position" / "gcat"
    gcat_dir.mkdir(parents=True)
    (gcat_dir / "satcat.tsv").write_text(_HEADER + "".join(r + "\n" for r in rows))
    return tmp_path


def test_zero_sizes_read_as_unknown(tmp_path):
    """A row GCAT has no figures for comes back with every size None."""
    root = _write_satcat(
        tmp_path,
        "S1\t22948\tRU\tSU\t-\t-\t0\t\t0\t\t0.0\t\t0.0\t\t0.0\t",
    )

    hardware = load_gcat_hardware(root)[22948]

    assert hardware.mass_kg is None
    assert hardware.dry_mass_kg is None
    assert hardware.length_m is None
    assert hardware.diameter_m is None
    assert hardware.span_m is None


def test_stated_sizes_survive(tmp_path):
    """Real figures pass through, including the sub-metre ones."""
    root = _write_satcat(
        tmp_path,
        "S2\t57521\tUS\tUS\t-\t-\t260\t\t248\t?\t0.3\t\t0.1\t\t1.0\t?",
    )

    hardware = load_gcat_hardware(root)[57521]

    assert hardware.mass_kg == 260.0
    assert hardware.dry_mass_kg == 248.0
    assert hardware.length_m == 0.3
    assert hardware.diameter_m == 0.1
    assert hardware.span_m == 1.0
    assert hardware.span_estimated is True
