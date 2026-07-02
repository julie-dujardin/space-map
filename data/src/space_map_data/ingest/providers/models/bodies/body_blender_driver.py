"""Blender headless driver for natural-body shape meshes.

Shape models are watertight scanned surfaces: weld seam duplicates (ICQ
cube-face borders), shade smooth, optionally decimate to a triangle budget,
export a single untextured mesh. Units are preserved (km); the ingest layer
records the true scale. No texture/double-sided handling — that's the
spacecraft driver's job.

Invoked via ``blender -b --python body_blender_driver.py -- <src> <dst.glb> [target_tris]``.
"""

import sys

import bmesh  # ty: ignore[unresolved-import]  # provided by Blender at runtime
import bpy  # ty: ignore[unresolved-import]  # provided by Blender at runtime


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(argv) not in (2, 3):
        raise SystemExit(
            "usage: blender -b --python body_blender_driver.py -- <src> <dst.glb> [target_tris]"
        )
    src, dst = argv[0], argv[1]
    target_tris = int(argv[2]) if len(argv) == 3 else 0

    bpy.ops.wm.read_factory_settings(use_empty=True)

    if src.lower().endswith(".obj"):
        # Shape OBJs are body-fixed Z-up (pole = +Z), not the OBJ default Y-up;
        # import axis-identity so export_yup applies the one body-Z→glTF-Y
        # rotation, matching the PLY/STL path and the textured-sphere frame.
        bpy.ops.wm.obj_import(filepath=src, up_axis="Z", forward_axis="Y")
    elif src.lower().endswith(".ply"):
        bpy.ops.wm.ply_import(filepath=src)
    elif src.lower().endswith(".stl"):
        bpy.ops.wm.stl_import(filepath=src)
    else:
        raise SystemExit(f"unsupported source format: {src}")

    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("no mesh objects after import")

    for obj in meshes:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.shade_smooth()

        tris = sum(max(len(p.vertices) - 2, 0) for p in obj.data.polygons)
        if target_tris and tris > target_tris:
            mod = obj.modifiers.new("decimate", "DECIMATE")
            mod.ratio = target_tris / tris
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=mod.name)

    # export_yup matches the spacecraft driver so the frontend loads both the
    # same way; km units survive (no export_apply scaling).
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", export_yup=True)


main()
