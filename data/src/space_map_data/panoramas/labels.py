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
        if self.frame not in {"SITE_FRAME", "LOCAL_LEVEL_FRAME"}:
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


def value(text: str, key: str) -> str:
    match = re.search(
        rf"^\s*{re.escape(key)}\s*=\s*(\([^)]*\)|\"[^\"]*\"|[^\r\n]+)",
        text,
        re.M,
    )
    if not match:
        raise ValueError(f"Missing PDS field: {key}")
    return match[1].strip().strip('"')


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


def read_pds3(text: str) -> Mosaic:
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
        (int(match[2]) - 1) * int(value(text, "RECORD_BYTES")),
        numbers(value(projection, "START_AZIMUTH"))[0],
        sx,
        sy,
        float(value(projection, "ZERO_ELEVATION_LINE")),
        value(projection, "REFERENCE_COORD_SYSTEM_NAME"),
        (
            float(value(text, "MISSING_CONSTANT")),
            float(value(text, "INVALID_CONSTANT")),
        ),
    )
    result.validate()
    return result


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
    raster = root.find(".//Array_3D_Image")
    if raster is None or get(raster, "axis_index_order") != "Last Index Fastest":
        raise ValueError("Unsupported raster layout")
    axes = sorted(
        raster.findall("Axis_Array"), key=lambda n: int(get(n, "sequence_number"))
    )
    if [get(n, "axis_name") for n in axes] != ["Band", "Line", "Sample"]:
        raise ValueError("Unsupported raster axes")
    bands, height, width = [int(get(n, "elements")) for n in axes]
    if get(raster, "Element_Array/data_type") != "SignedMSB2":
        raise ValueError("Unsupported PDS4 sample type")
    result = Mosaic(
        product_id,
        int(get(root, ".//start_sol_number")),
        site,
        drive,
        get(root, ".//start_date_time"),
        get(root, ".//stop_date_time"),
        width,
        height,
        bands,
        ">i2",
        int(get(raster, "offset")),
        float(get(projection, ".//start_azimuth")),
        float(get(projection, ".//pixel_scale_x")),
        float(get(projection, ".//pixel_scale_y")),
        float(get(projection, ".//zero_elevation_line")),
        frame,
        tuple(
            float(get(raster, f"Special_Constants/{k}"))
            for k in ("missing_constant", "invalid_constant")
        ),
    )
    result.validate()
    return result
