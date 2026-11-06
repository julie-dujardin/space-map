"""Helpers shared by the export tests."""

from dataclasses import fields

from space_map_data.export.systems import TextureLayers


def layers_of(textures: dict | None = None, **layers: dict) -> TextureLayers:
    """Texture layers with these surface maps and other layers, the rest
    empty."""
    empty: dict = {f.name: {} for f in fields(TextureLayers)}
    return TextureLayers(**(empty | {"textures": textures or {}} | layers))
