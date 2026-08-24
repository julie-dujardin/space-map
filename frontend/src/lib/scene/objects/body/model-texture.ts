import { Mesh, MeshStandardMaterial, type Object3D, SRGBColorSpace, type Texture } from 'three';
import { tintBaseColor } from './texture-tint';
import { tagShaderModifier } from '$lib/scene/shaders/program-cache-key';

/**
 * Equirectangular `map` sampling for shape-model meshes, which ship no texture
 * coordinates. GLB's body-fixed frame (glTF +Y = north, +X = prime meridian,
 * -Z = east) matches the textured sphere's, so projecting the fragment
 * direction onto lat/lon (u = lon/2π + 0.5, matching SphereGeometry's UVs)
 * samples the same map correctly.
 *
 * Per-fragment, not baked per vertex, so triangles crossing the ±180° meridian
 * don't smear; samples with gradients from whichever of two half-offset
 * longitude parameterisations is locally continuous, to dodge the wrap seam.
 */
const EQUIRECT_MAP_FRAGMENT = /* glsl */ `
#ifdef USE_MAP
	vec3 bodyDir = normalize( vBodyDir );
	float lon = atan( -bodyDir.z, bodyDir.x );
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
	const material = new MeshStandardMaterial({
		color,
		roughness: 1,
		metalness: 0
	});
	material.onBeforeCompile = (shader) => {
		shader.vertexShader = shader.vertexShader
			.replace('#include <common>', '#include <common>\nvarying vec3 vBodyDir;')
			.replace('#include <begin_vertex>', '#include <begin_vertex>\nvBodyDir = position;');
		shader.fragmentShader = shader.fragmentShader
			.replace('#include <common>', '#include <common>\nvarying vec3 vBodyDir;')
			.replace('#include <map_fragment>', EQUIRECT_MAP_FRAGMENT)
			// No IBL fill, matching the sphere path's nightside — the overlay's env
			// map is for metallic spacecraft, not matte bodies. Stubbed in-shader
			// because a scene-level environment forces envMapIntensity from
			// scene.environmentIntensity, ignoring the material's own opt-out.
			.replace(
				'#include <envmap_physical_pars_fragment>',
				/* glsl */ `
				#ifdef USE_ENVMAP
					vec3 getIBLIrradiance( const in vec3 normal ) { return vec3( 0.0 ); }
					vec3 getIBLRadiance( const in vec3 viewDir, const in vec3 normal, const in float roughness ) { return vec3( 0.0 ); }
				#endif`
			);
	};
	// Named so a chained modifier (eclipse, in the main scene) can't collide
	// with a sphere material ending in the same hook.
	tagShaderModifier(material, 'shapeModel');
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
 * Point the model's materials at `map` (colour-space-tagged by the sphere
 * path; shared not copied, so texture-tier upgrades propagate by re-calling
 * this). `null` reverts to `fallbackColor`. Base colour follows
 * `tintBaseColor`: a grayscale map is tinted by `tintHex`, a coloured one stays as-is.
 */
export function setShapeModelMap(
	root: Object3D,
	map: Texture | null,
	fallbackColor: string | number,
	tintHex?: string
): void {
	root.traverse((obj) => {
		if (!(obj instanceof Mesh) || !(obj.material instanceof MeshStandardMaterial)) return;
		obj.material.map = map;
		if (map) obj.material.color.copy(tintBaseColor(map, tintHex));
		else obj.material.color.set(fallbackColor);
		obj.material.needsUpdate = true;
	});
}

/**
 * Sphere-side counterpart of {@link setShapeModelMap}, shared by the focused
 * scene and the lineup so identical bodies colour identically. Tags sRGB,
 * disposes any prior map, and applies the same grayscale-tint rule as above.
 */
export function setSurfaceMap(
	material: MeshStandardMaterial,
	map: Texture,
	tintHex?: string
): void {
	if (material.map && material.map !== map) material.map.dispose();
	map.colorSpace = SRGBColorSpace;
	material.map = map;
	material.color.copy(tintBaseColor(map, tintHex));
	material.needsUpdate = true;
}
