"""HDR equirect EXR: a streaming loader with Reinhard tonemap for the cube
tiers, and a reader by window for the tile pyramid."""

import logging
import threading
from collections import OrderedDict
from pathlib import Path

import Imath
import numpy as np
import OpenEXR  # ty: ignore[unresolved-import]  # C extension, no stubs

from .encoding import linear_to_srgb, srgb_to_linear

log = logging.getLogger(__name__)

# Number of *output* rows tonemapped per streaming band. At 16K output width
# with 4× downsample, each band reads 256×4 = 1024 source scanlines per
# channel (~128 MiB of half-float source data per band).
_BAND_OUT_ROWS = 256
# Scanlines that ``ExrRaster`` decodes at a time, and the bytes it keeps
# decoded. A row of cap tiles through a pole reads the scanlines from the
# pole to 46° at once: 3.3 GiB of a 64K map. A row of map tiles reads 0.4 GiB.
_RASTER_BAND_ROWS = 64
_RASTER_CACHE_BYTES = 7 << 29


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


class ExrRaster:
    """An RGB half-float EXR read by window like an array, as (H, W, 3).

    The file is 12 GiB decoded, and the EXR reader gives whole scanlines
    only. A read decodes the bands of scanlines under it, and the last bands
    stay decoded for the reads beside it.
    """

    def __init__(self, src: Path) -> None:
        self._file = OpenEXR.InputFile(str(src))
        window = self._file.header()["dataWindow"]
        self._top = window.min.y
        self.shape: tuple[int, int, int] = (
            window.max.y - window.min.y + 1,
            window.max.x - window.min.x + 1,
            3,
        )
        self.dtype = np.dtype(np.float16)
        self._cache: OrderedDict[int, np.ndarray] = OrderedDict()
        self._held = 0
        # The reader is not safe to share between threads.
        self._lock = threading.Lock()

    def _band(self, index: int) -> np.ndarray:
        with self._lock:
            band = self._cache.get(index)
            if band is not None:
                self._cache.move_to_end(index)
                return band
            height, width, _ = self.shape
            y0 = index * _RASTER_BAND_ROWS
            y1 = min(y0 + _RASTER_BAND_ROWS, height)
            half = Imath.PixelType(Imath.PixelType.HALF)
            band = np.empty((y1 - y0, width, 3), dtype=np.float16)
            # One call: each call inflates the scanlines again.
            raws = self._file.channels("RGB", half, self._top + y0, self._top + y1 - 1)
            for channel, raw in enumerate(raws):
                band[..., channel] = np.frombuffer(raw, np.float16).reshape(
                    y1 - y0, width
                )
            self._cache[index] = band
            self._held += band.nbytes
            while self._held > _RASTER_CACHE_BYTES and len(self._cache) > 1:
                self._held -= self._cache.popitem(last=False)[1].nbytes
            return band

    def __getitem__(self, key: tuple[slice, slice]) -> np.ndarray:
        y0, y1, _ = key[0].indices(self.shape[0])
        x0, x1, _ = key[1].indices(self.shape[1])
        out = np.empty((max(y1 - y0, 0), max(x1 - x0, 0), 3), dtype=np.float16)
        rows = _RASTER_BAND_ROWS
        for index in range(y0 // rows, -(-y1 // rows)):
            band = self._band(index)
            top, bottom = max(y0, index * rows), min(y1, index * rows + band.shape[0])
            out[top - y0 : bottom - y0] = band[
                top - index * rows : bottom - index * rows, x0:x1
            ]
        return out

    def release(self) -> None:
        """Drop the decoded bands."""
        with self._lock:
            self._cache.clear()
            self._held = 0


def load_and_tonemap_streaming(src: Path, ds: int, exposure: float) -> np.ndarray:
    """Stream-read an HDR equirect EXR and tonemap to a downsampled uint8 equirect.

    Returns (H/ds, W/ds, 3) uint8 in sRGB-encoded values. Reads source
    scanlines in chunks via OpenEXR's ``InputFile.channel`` so peak working
    memory stays well under the full uncompressed pixel size (12+ GiB for
    64K×32K half-float).

    The Reinhard tonemap with exposure pre-multiplier ``exposure``
    lifts faint Milky Way structure above the toe before compression to
    [0, 1). sRGB encoding follows so the resulting WebP samples correctly
    under Three.js' default sRGB texture path.
    """
    inp = OpenEXR.InputFile(str(src))
    hdr = inp.header()
    dw = hdr["dataWindow"]
    src_w = dw.max.x - dw.min.x + 1
    src_h = dw.max.y - dw.min.y + 1
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

        np.multiply(band, exposure, out=band)
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


def mean_down(face: np.ndarray, factor: int) -> np.ndarray:
    """Average a uint8 sRGB face over ``factor``² blocks in linear light, as a
    GPU makes the mips of an sRGB texture."""
    size = face.shape[0] // factor
    linear = srgb_to_linear(face.astype(np.float32) / 255.0)
    mean = linear.reshape(size, factor, size, factor, 3).mean(axis=(1, 3))
    return (np.clip(linear_to_srgb(mean), 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
