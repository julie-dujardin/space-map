"""Read the supported PDS cylindrical intensity mosaics."""

from dataclasses import dataclass
import math
import re
import xml.etree.ElementTree as ET


@dataclass
class Mosaic:
    product_id: str
    sol: int
    site: int
    drive: int
    start_time: str
    stop_time: str
    width: int
    height: int
    bands: int
    dtype: str
    offset: int
    azimuth: float
    scale_x: float
    scale_y: float
    zero_line: float
    frame: str
    missing: tuple[float, ...]

    def validate(self):
        if self.frame not in {"SITE_FRAME", "LOCAL_LEVEL_FRAME", "LANDER_FRAME"}:
            raise ValueError(f"Unsupported orientation frame: {self.frame}")
        if self.bands not in (1, 3) or min(self.width, self.height) < 1:
            raise ValueError("Expected a mono or RGB image")
        if (
            self.offset < 0
            or not all(
                math.isfinite(v)
                for v in (self.azimuth, self.scale_x, self.scale_y, self.zero_line)
            )
            or min(self.scale_x, self.scale_y) <= 0
        ):
            raise ValueError("Invalid raster geometry")
        if self.width / self.scale_x > 360 + 2 / self.scale_x:
            raise ValueError("Horizontal coverage exceeds one revolution")


def optional(text: str, key: str) -> str | None:
    match = re.search(
        rf"^\s*{re.escape(key)}\s*=\s*(\([^)]*\)|\"[^\"]*\"|[^\r\n]+)",
        text,
        re.M,
    )
    return match[1].strip().strip('"') if match else None


def value(text: str, key: str) -> str:
    found = optional(text, key)
    if found is None:
        raise ValueError(f"Missing PDS field: {key}")
    return found


SPECIAL_CONSTANTS = ("MISSING_CONSTANT", "INVALID_CONSTANT")


def detached_constants(text: str) -> tuple[float, ...]:
    """Empty when the detached label declares no special values; never a partial pair."""
    found = [optional(text, key) for key in SPECIAL_CONSTANTS]
    return tuple(float(v) for v in found if v is not None) if None not in found else ()


def attached_constants(header: str) -> tuple[float, ...]:
    """MSL detached labels stopped declaring the special values the VICAR header keeps."""
    found = []
    for key in SPECIAL_CONSTANTS:
        match = re.search(rf"(?<![A-Z_]){key}\s*=\s*([-+\d.eE]+)", header)
        if match is None:
            raise ValueError(f"Missing attached header field: {key}")
        found.append(float(match[1]))
    return tuple(found)


def numbers(text: str) -> list[float]:
    return [
        float(n)
        for n in re.findall(
            r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", re.sub(r"<[^>]+>", "", text)
        )
    ]


def block(text: str, kind: str, name: str) -> str:
    match = re.search(
        rf"^\s*{kind}\s*=\s*{name}\s*$([\s\S]*?)^\s*END_{kind}\s*=",
        text,
        re.M,
    )
    if not match:
        raise ValueError(f"Missing PDS block: {name}")
    return match[1]


def cylindrical_blocks(text: str) -> tuple[str, str]:
    """The projection and raster blocks, once the mosaic is known to be supported."""
    projection = block(text, "GROUP", "SURFACE_PROJECTION_PARMS")
    raster = block(text, "OBJECT", "IMAGE")
    if value(projection, "MAP_PROJECTION_TYPE") != "CYLINDRICAL":
        raise ValueError("Only angular cylindrical mosaics are supported")
    if value(raster, "BAND_STORAGE_TYPE") != "BAND_SEQUENTIAL":
        raise ValueError("Unsupported band storage")
    if (
        value(raster, "SAMPLE_TYPE") != "MSB_INTEGER"
        or value(raster, "SAMPLE_BITS") != "16"
    ):
        raise ValueError("Unsupported PDS3 sample type")
    return projection, raster


def pds3_mosaic(text, projection, raster, *, site, drive, offset) -> Mosaic:
    """A validated mosaic, given the rover position and raster offset its
    archive states in its own way."""
    sx, sy = numbers(value(projection, "MAP_RESOLUTION"))
    result = Mosaic(
        value(text, "PRODUCT_ID"),
        int(value(text, "PLANET_DAY_NUMBER")),
        site,
        drive,
        value(text, "START_TIME"),
        value(text, "STOP_TIME"),
        int(value(raster, "LINE_SAMPLES")),
        int(value(raster, "LINES")),
        int(value(raster, "BANDS")),
        ">i2",
        offset,
        numbers(value(projection, "START_AZIMUTH"))[0],
        sx,
        sy,
        numbers(value(projection, "ZERO_ELEVATION_LINE"))[0],
        value(projection, "REFERENCE_COORD_SYSTEM_NAME"),
        detached_constants(text),
    )
    result.validate()
    return result


def read_pds3(text: str) -> Mosaic:
    projection, raster = cylindrical_blocks(text)
    sources = value(text, "SOURCE_PRODUCT_ID")
    counters = set(re.findall(r"_F(\d{3})(\d{4})", sources))
    if len(counters) != 1:
        raise ValueError("Source frames span multiple or unknown rover positions")
    site, drive = map(int, counters.pop())
    if site != int(value(projection, "REFERENCE_COORD_SYSTEM_INDEX")):
        raise ValueError("Source and projection site mismatch")
    pointer = value(text, "^IMAGE")
    match = re.fullmatch(r'\("([^"/]+)"\s*,\s*(\d+)\)', pointer)
    if not match or match[1] != value(text, "PRODUCT_ID") + ".IMG":
        raise ValueError("Unsupported image pointer")
    return pds3_mosaic(
        text,
        projection,
        raster,
        site=site,
        drive=drive,
        offset=(int(match[2]) - 1) * int(value(text, "RECORD_BYTES")),
    )


def read_mer_pds3(text: str, drive: int) -> Mosaic:
    """A Mars Exploration Rover mosaic, whose label is attached to its raster.

    The label states the site its projection is referenced to but not the drive
    within it, which only the pointing-correction file beside it records.
    """
    projection, raster = cylindrical_blocks(text)
    pointer = value(text, "^IMAGE")
    if not re.fullmatch(r"\d+", pointer):
        raise ValueError("Unsupported image pointer")
    return pds3_mosaic(
        text,
        projection,
        raster,
        site=int(value(projection, "REFERENCE_COORD_SYSTEM_INDEX")),
        drive=drive,
        offset=(int(pointer) - 1) * int(value(text, "RECORD_BYTES")),
    )


def pds4_field(node, path):
    found = node.find(path)
    if found is None or found.text is None:
        raise ValueError(f"Missing PDS4 field: {path}")
    return found.text.strip()


# Every sample type the supported PDS4 mosaics are stored in.
PDS4_SAMPLES = {
    "UnsignedByte": "|u1",
    "SignedLSB2": "<i2",
    "SignedMSB2": ">i2",
    "UnsignedLSB2": "<u2",
    "UnsignedMSB2": ">u2",
}


def pds4_raster(root, get, samples: dict[str, str]):
    """The raster a PDS4 mosaic points at, once its samples are supported."""
    raster = root.find(".//Array_3D_Image")
    if raster is None or get(raster, "axis_index_order") != "Last Index Fastest":
        raise ValueError("Unsupported raster layout")
    axes = sorted(
        raster.findall("Axis_Array"), key=lambda n: int(get(n, "sequence_number"))
    )
    if [get(n, "axis_name") for n in axes] != ["Band", "Line", "Sample"]:
        raise ValueError("Unsupported raster axes")
    sample = get(raster, "Element_Array/data_type")
    if sample not in samples:
        raise ValueError(f"Unsupported PDS4 sample type: {sample}")
    return raster, [int(get(n, "elements")) for n in axes], samples[sample]


def pds4_mosaic(root, get, projection, raster, shape, *, site, drive, dtype) -> Mosaic:
    bands, height, width = shape
    result = Mosaic(
        get(root, ".//alternate_id"),
        int(get(root, ".//start_sol_number")),
        site,
        drive,
        get(root, ".//start_date_time"),
        get(root, ".//stop_date_time"),
        width,
        height,
        bands,
        dtype,
        int(get(raster, "offset")),
        float(get(projection, ".//start_azimuth")),
        float(get(projection, ".//pixel_scale_x")),
        float(get(projection, ".//pixel_scale_y")),
        float(get(projection, ".//zero_elevation_line")),
        get(projection, ".//coordinate_space_frame_type"),
        tuple(
            float(get(raster, f"Special_Constants/{k}"))
            for k in ("missing_constant", "invalid_constant")
        ),
    )
    result.validate()
    return result


def read_insight_pds4(text: str) -> Mosaic:
    """An InSight mosaic, which never moved and says so.

    The lander's projection is the one Perseverance uses, referenced to a frame
    that cannot travel: its site and drive are fixed, and its place is the
    landing site rather than anything a localization states.
    """
    root = ET.fromstring(text)
    for node in root.iter():
        node.tag = node.tag.split("}")[-1]
    get = pds4_field
    projection = root.find(".//Map_Projection_Lander")
    if (
        projection is None
        or get(projection, "lander_map_projection_name") != "Cylindrical"
    ):
        raise ValueError("Only angular cylindrical mosaics are supported")
    if "CYL" not in get(root, ".//alternate_id"):
        raise ValueError("Unsupported InSight product identity")
    if get(root, ".//derived_image_type_name") != "IMAGE":
        raise ValueError("Not an intensity product")
    indices = {
        get(n, "index_id"): int(get(n, "index_value_number"))
        for n in projection.findall(".//Coordinate_Space_Index")
    }
    raster, shape, dtype = pds4_raster(root, get, PDS4_SAMPLES)
    return pds4_mosaic(
        root,
        get,
        projection,
        raster,
        shape,
        site=indices.get("SITE", 0),
        drive=indices.get("DRIVE", 0),
        dtype=dtype,
    )


def read_pds4(text: str) -> Mosaic:
    root = ET.fromstring(text)
    for node in root.iter():
        node.tag = node.tag.split("}")[-1]

    def get(node, path):
        found = node.find(path)
        if found is None or found.text is None:
            raise ValueError(f"Missing PDS4 field: {path}")
        return found.text.strip()

    projection = root.find(".//Map_Projection_Lander")
    if (
        projection is None
        or get(projection, "lander_map_projection_name") != "Cylindrical"
    ):
        raise ValueError("Only angular cylindrical mosaics are supported")
    frame = get(projection, ".//coordinate_space_frame_type")
    indices = {
        get(n, "index_id"): int(get(n, "index_value_number"))
        for n in projection.findall(".//Coordinate_Space_Index")
    }
    product_id = get(root, ".//alternate_id")
    counter = re.fullmatch(r"N_LRGB_\d+[X_]RZS_(\d{3})(\d{4})_CYL_[LS]_\w+", product_id)
    if counter is None:
        raise ValueError("Unsupported Perseverance product identity")
    site, drive = map(int, counter.groups())
    if indices.get("SITE") != site or indices.get("DRIVE", drive) != drive:
        raise ValueError("Product and projection rover position mismatch")
    source_ids = [
        get(n, ".//lidvid_reference")
        for n in root.findall(".//Input_Product_List/Input_Product")
    ]
    counters = set(re.findall(r"_n(\d{3})(\d{4})", " ".join(source_ids)))
    if counters != {(f"{site:03}", f"{drive:04}")}:
        raise ValueError("Source frames span multiple or unknown rover positions")
    if frame == "LOCAL_LEVEL_FRAME":
        local_id = "LOCAL_LEVEL_FRAME_" + "_".join(
            str(indices[k]) for k in ("SITE", "DRIVE", "POSE")
        )
        definition = next(
            (
                n
                for n in root.findall(".//Coordinate_Space_Definition")
                if get(n, "local_identifier") == local_id
            ),
            None,
        )
        if definition is None:
            raise ValueError("Missing local-level orientation")
        quaternion = [
            float(get(definition, f".//{k}"))
            for k in ("qcos", "qsin1", "qsin2", "qsin3")
        ]
        if (
            quaternion != [1, 0, 0, 0]
            or get(
                definition, "Coordinate_Space_Reference//coordinate_space_frame_type"
            )
            != "SITE_FRAME"
        ):
            raise ValueError("Local-level frame is not aligned to site north")
    if get(root, ".//derived_image_type_name") != "IMAGE":
        raise ValueError("Not an intensity product")
    raster, shape, dtype = pds4_raster(root, get, {"SignedMSB2": ">i2"})
    return pds4_mosaic(
        root, get, projection, raster, shape, site=site, drive=drive, dtype=dtype
    )
