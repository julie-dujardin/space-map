"""Blender headless driver: import a source mesh, export to glTF binary.

Invoked via ``blender -b --python blender_driver.py -- <src> <dst>``.
Runs in Blender's embedded Python, so only ``bpy`` and stdlib are available.
"""

import os
import sys

import bpy  # ty: ignore[unresolved-import]  # provided by Blender at runtime


def _parse_args() -> tuple[str, str]:
    if "--" not in sys.argv:
        raise SystemExit("usage: blender -b --python blender_driver.py -- <src> <dst>")
    after = sys.argv[sys.argv.index("--") + 1 :]
    if len(after) != 2:
        raise SystemExit("expected two positional args: <src> <dst>")
    return after[0], after[1]


def _clear_scene() -> None:
    """Drop every object Blender ships in the default scene before importing."""
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _patch_fbx_importer() -> None:
    """Work around a Blender 5.x bug in the bundled FBX importer.

    ``io_scene_fbx.import_fbx.blen_read_light`` assigns to
    ``lamp.cycles.cast_shadow``, an attribute removed in Blender 5.x. Any FBX
    containing a light fails with ``AttributeError`` and the whole import
    aborts. We don't care about Cycles render settings (headless glTF export),
    so wrap ``blen_read_light`` to swallow that one error and let the rest of
    the import proceed.
    """
    try:
        import io_scene_fbx.import_fbx as fbx  # ty: ignore[unresolved-import]  # Blender add-on
    except ImportError:
        return  # FBX add-on not loaded (we only need this for .fbx imports)
    original = getattr(fbx, "blen_read_light", None)
    if original is None:
        return

    def patched(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except AttributeError as exc:
            if "cast_shadow" in str(exc):
                return None  # leave the half-built lamp; nobody downstream cares
            raise

    fbx.blen_read_light = patched


def _import(path: str) -> None:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext == "fbx":
        _patch_fbx_importer()
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == "obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == "3ds":
        bpy.ops.import_scene.max3ds(filepath=path)
    elif ext == "blend":
        # Open the .blend directly — link the scene's objects into the current
        # scene rather than loading the whole file (which would replace the
        # empty factory scene we set up). Append everything from the source
        # file's first scene.
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        scene = bpy.context.scene
        for obj in dst.objects:
            if obj is not None:
                scene.collection.objects.link(obj)
    else:
        raise SystemExit(f"unsupported source format: {ext}")


def _export_glb(path: str) -> None:
    """Export the scene as a glb without animations or morph targets.

    The frontend renders all spacecraft models as static meshes, so
    animation data is dead weight. Disabling it also sidesteps a Blender
    5.x glTF exporter crash on meshes with animation data but no shape
    keys (``NoneType`` has no ``key_blocks`` — e.g. NASA's InSight Cruise
    Lander .blend variants); the operator catches that AttributeError
    internally and returns ``CANCELLED``, so Python-side try/except can't
    recover.
    """
    bpy.ops.export_scene.gltf(
        filepath=path,
        export_format="GLB",
        export_apply=True,
        export_yup=True,
        export_extras=False,
        export_animations=False,
        export_morph=False,
        export_image_format="AUTO",
    )


def main() -> None:
    src, dst = _parse_args()
    _clear_scene()
    _import(src)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    _export_glb(dst)


main()
