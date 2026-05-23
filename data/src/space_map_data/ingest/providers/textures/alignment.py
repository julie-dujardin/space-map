"""Cylindrical equirectangular alignment to the renderer's convention."""

from PIL import Image

DEFAULT_ALIGNMENT = {"west_positive": False, "lon_at_left_deg": -180.0}


def entry_alignment(entry: dict) -> dict:
    """Extract cylindrical-alignment fields from a yaml entry.

    Defaults match the renderer's expected convention (no flip, prime
    meridian at the image centre) so untagged entries are no-ops.
    """
    return {
        "west_positive": bool(entry.get("west_positive", False)),
        "lon_at_left_deg": float(entry.get("lon_at_left_deg", -180.0)),
    }


def align_cylindrical(
    img: Image.Image, *, west_positive: bool, lon_at_left_deg: float
) -> Image.Image:
    """Transform a cylindrical equirectangular image to the renderer's convention.

    The renderer (frontend/src/lib/math/orientation.ts) expects u=0 at
    longitude -180°, u=0.5 at 0° (prime meridian), and longitude increasing
    east with u.

    Two corrections applied in order:
      1. ``west_positive``: horizontally mirror W+ IAU sources (Jovian /
         Saturnian satellites, gas giants under System III) so the result is
         east-positive.
      2. ``lon_at_left_deg``: east-positive longitude at the source's left
         edge *after* any flip. The image is circularly shifted so this lands
         at -180°. Default -180° → no shift.
    """
    if west_positive:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

    w, h = img.size
    shift_px = round((lon_at_left_deg + 180.0) / 360.0 * w) % w
    if shift_px == 0:
        return img

    left = img.crop((0, 0, w - shift_px, h))
    right = img.crop((w - shift_px, 0, w, h))
    out = Image.new(img.mode, (w, h))
    out.paste(right, (0, 0))
    out.paste(left, (shift_px, 0))
    return out
