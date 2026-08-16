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
    """Work around a Blender 5.x bug: FBX import aborts on lights.

    ``blen_read_light`` assigns to ``lamp.cycles.cast_shadow``, removed in
    Blender 5.x, raising ``AttributeError``. Cycles settings don't matter for
    headless glTF export, so swallow that one error and let import proceed.
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
        # Link objects into the current scene rather than opening the file,
        # which would replace the empty factory scene set up above.
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            dst.objects = list(src.objects)
        scene = bpy.context.scene
        for obj in dst.objects:
            if obj is not None:
                scene.collection.objects.link(obj)
    else:
        raise SystemExit(f"unsupported source format: {ext}")


def _force_double_sided() -> None:
    """Disable backface culling on every material.

    Some source FBX models (e.g. ESA's INTEGRAL) have inward-facing normals;
    glTF's default single-sided rendering would cull the visible surface and
    show the textured inside instead. Forcing doubleSided avoids having to
    detect which parts have inverted normals.
    """
    for mat in bpy.data.materials:
        mat.use_backface_culling = False


def _force_opaque() -> None:
    """Force every Principled BSDF's Alpha to 1.0.

    The FBX importer wires Alpha from each texture's alpha channel even when
    the source PNGs are opaque with garbage in that channel, so the exported
    glTF ends up ``alphaMode: BLEND`` and Three.js renders the model
    see-through (seen on ESA's INTEGRAL). None of the catalog models are
    meant to have alpha.
    """
    for mat in bpy.data.materials:
        if not mat.use_nodes or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue
            alpha = node.inputs.get("Alpha")
            if alpha is None:
                continue
            for link in list(alpha.links):
                mat.node_tree.links.remove(link)
            alpha.default_value = 1.0


def _export_glb(path: str) -> None:
    """Export the scene as a glb without animations or morph targets.

    The frontend renders spacecraft as static meshes, so animation data is
    dead weight. This also sidesteps a Blender 5.x exporter crash on meshes
    with animation data but no shape keys (e.g. NASA's InSight Cruise Lander
    .blend files) — the operator swallows that error and returns
    ``CANCELLED`` instead of raising, so it can't be caught from Python.
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
    _force_double_sided()
    _force_opaque()
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    _export_glb(dst)


main()
