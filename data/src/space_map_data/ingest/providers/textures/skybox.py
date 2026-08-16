"""HDR equirect EXR streaming loader with Reinhard tonemap."""

import logging
from pathlib import Path

import Imath
import numpy as np
import OpenEXR  # ty: ignore[unresolved-import]  # C extension, no stubs

from . import config
from .encoding import linear_to_srgb

log = logging.getLogger(__name__)

# Number of *output* rows tonemapped per streaming band. At 16K output width
# with 4× downsample, each band reads 256×4 = 1024 source scanlines per
# channel (~128 MiB of half-float source data per band).
_BAND_OUT_ROWS = 256


def mem_available_bytes() -> int | None:
    """Return MemAvailable from /proc/meminfo in bytes, or None if unreadable.

    Used as a coarse pre-flight check before loading multi-gigabyte EXRs.
    Returns None on non-Linux platforms or if the file is missing — callers
    treat None as "don't know, proceed".
    """
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    parts = line.split()
                    return int(parts[1]) * 1024  # kB → bytes
    except OSError:
        return None
    return None


def load_and_tonemap_streaming(src: Path) -> np.ndarray:
    """Stream-read an HDR equirect EXR and tonemap to a downsampled uint8 equirect.

    Returns (H/ds, W/ds, 3) uint8 in sRGB-encoded values, where ``ds`` is
    ``config.SKYBOX_DOWNSAMPLE``. Reads source scanlines in chunks via
    OpenEXR's ``InputFile.channel`` so peak working memory stays well under
    the full uncompressed pixel size (12+ GiB for 64K×32K half-float).

    The Reinhard tonemap with exposure pre-multiplier (``SKYBOX_EXPOSURE``)
    lifts faint Milky Way structure above the toe before compression to
    [0, 1). sRGB encoding follows so the resulting WebP samples correctly
    under Three.js' default sRGB texture path.
    """
    inp = OpenEXR.InputFile(str(src))
    hdr = inp.header()
    dw = hdr["dataWindow"]
    src_w = dw.max.x - dw.min.x + 1
    src_h = dw.max.y - dw.min.y + 1
    ds = config.SKYBOX_DOWNSAMPLE
    if src_w % ds or src_h % ds:
        raise ValueError(
            f"{src.name}: dims {src_w}x{src_h} not divisible by downsample {ds}"
        )
    out_w, out_h = src_w // ds, src_h // ds
    out = np.empty((out_h, out_w, 3), dtype=np.uint8)
    pt = Imath.PixelType(Imath.PixelType.HALF)

    log.info(
        "streaming EXR %dx%d → %dx%d uint8 (%dx downsample, %d bands)",
        src_w,
        src_h,
        out_w,
        out_h,
        ds,
        (out_h + _BAND_OUT_ROWS - 1) // _BAND_OUT_ROWS,
    )

    for out_y0 in range(0, out_h, _BAND_OUT_ROWS):
        out_y1 = min(out_y0 + _BAND_OUT_ROWS, out_h)
        band_out_h = out_y1 - out_y0
        src_y0 = out_y0 * ds
        src_y1 = src_y0 + band_out_h * ds - 1  # inclusive

        channels: list[np.ndarray] = []
        for name in ("R", "G", "B"):
            raw = inp.channel(name, pt, src_y0, src_y1)
            ch = np.frombuffer(raw, dtype=np.float16).reshape(band_out_h * ds, src_w)
            channels.append(ch)

        # Cast to float32 first so bright-star half-float values aggregate
        # without saturation bias.
        rgb_src = np.stack(channels, axis=-1).astype(np.float32, copy=False)
        del channels
        band = rgb_src.reshape(band_out_h, ds, out_w, ds, 3).mean(
            axis=(1, 3), dtype=np.float32
        )
        del rgb_src

        np.multiply(band, config.SKYBOX_EXPOSURE, out=band)
        np.clip(band, 0.0, None, out=band)
        denom = band + 1.0
        np.divide(band, denom, out=band)
        del denom
        srgb = linear_to_srgb(band)
        np.clip(srgb, 0.0, 1.0, out=srgb)
        np.multiply(srgb, 255.0, out=srgb)
        np.add(srgb, 0.5, out=srgb)
        out[out_y0:out_y1] = srgb.astype(np.uint8, copy=False)
        del band, srgb

    inp.close()
    return out
