import { Mesh, MeshStandardMaterial, type Object3D, type Texture } from 'three';

/**
 * Equirectangular `map` sampling for shape-model meshes, which ship no texture
 * coordinates. The GLB's body-fixed frame (glTF +Y = north pole, +X = prime
 * meridian) matches the frame the textured sphere renders, so projecting the
 * fragment's direction onto lat/lon samples the same surface map correctly.
 *
 * Sampling happens per fragment (not baked per vertex) so triangles crossing
 * the ±180° meridian don't smear; the wrap's derivative discontinuity is
 * handled by sampling with gradients from whichever of two half-offset
 * longitude parameterisations is locally continuous.
 */
const EQUIRECT_MAP_FRAGMENT = /* glsl */ `
#ifdef USE_MAP
	vec3 bodyDir = normalize( vBodyDir );
	float lon = atan( bodyDir.z, -bodyDir.x );
	vec2 euv = vec2( lon / ( 2.0 * PI ) + 0.5, 1.0 - acos( clamp( bodyDir.y, -1.0, 1.0 ) ) / PI );
	vec2 euvB = vec2( fract( euv.x + 0.5 ), euv.y );
	vec2 dxA = dFdx( euv ), dyA = dFdy( euv );
	vec2 dxB = dFdx( euvB ), dyB = dFdy( euvB );
	bool seam = dot( dxA, dxA ) + dot( dyA, dyA ) > dot( dxB, dxB ) + dot( dyB, dyB );
	vec4 sampledDiffuseColor = textureGrad( map, euv, seam ? dxB : dxA, seam ? dyB : dyA );
	diffuseColor *= sampledDiffuseColor;
#endif
`;

/**
 * Material for a shape-model mesh: flat body tint until a surface map arrives
 * (via {@link setShapeModelMap}), then the map projected equirectangularly.
 */
export function makeShapeModelMaterial(color: string | number): MeshStandardMaterial {
	const material = new MeshStandardMaterial({ color, roughness: 1, metalness: 0 });
	material.onBeforeCompile = (shader) => {
		shader.vertexShader = shader.vertexShader
			.replace('#include <common>', '#include <common>\nvarying vec3 vBodyDir;')
			.replace('#include <begin_vertex>', '#include <begin_vertex>\nvBodyDir = position;');
		shader.fragmentShader = shader.fragmentShader
			.replace('#include <common>', '#include <common>\nvarying vec3 vBodyDir;')
			.replace('#include <map_fragment>', EQUIRECT_MAP_FRAGMENT);
	};
	return material;
}

/** Swap every material under `root` for one shared shape-model material. */
export function applyShapeModelMaterial(root: Object3D, material: MeshStandardMaterial): void {
	root.traverse((obj) => {
		if (!(obj instanceof Mesh)) return;
		const old = obj.material;
		obj.material = material;
		const list = Array.isArray(old) ? old : [old];
		for (const m of list) m?.dispose();
	});
}

/**
 * Point the model's materials at `map` (already colour-space-tagged by the
 * sphere path — the Texture object is shared, not copied, so texture-tier
 * upgrades propagate by re-calling this). `null` reverts to `fallbackColor`.
 */
export function setShapeModelMap(
	root: Object3D,
	map: Texture | null,
	fallbackColor: string | number
): void {
	root.traverse((obj) => {
		if (!(obj instanceof Mesh) || !(obj.material instanceof MeshStandardMaterial)) return;
		obj.material.map = map;
		obj.material.color.set(map ? 0xffffff : fallbackColor);
		obj.material.needsUpdate = true;
	});
}
