import { type MeshStandardMaterial, NoColorSpace, type Texture, type TextureLoader } from 'three';
import { versionedUrl } from '$lib/fetch/data-base';
import { kmToScene } from '$lib/math/units';

/**
 * Per-body displacement metadata from `systems/{bary}.json` (see
 * `export/systems.py::displacement_block`). `scale_km`/`bias_km` map each texel
 * to a value: `km = bias_km + scale_km * texel`. When `absolute_radius`, that
 * value is radius-from-centre (not elevation), so the caller renders the body
 * as a sphere + displacement and subtracts its own radius — see
 * {@link attachDisplacementMap}.
 */
export interface DisplacementMeta {
	id: string;
	tiers: string[];
	scale_km: number;
	bias_km: number;
	absolute_radius: boolean;
	source: string;
	organisation: string;
	type: string;
	attribution?: string;
	description?: string;
}

/**
 * Load a body's height map onto a `MeshStandardMaterial` as a displacement map
 * at true scale. Scale/bias are in scene units, so the per-frame sphere-LOD
 * geometry swap displaces correctly at every tessellation level. `NoColorSpace`:
 * it's linear height data, not colour.
 *
 * For `absolute_radius` grids the values are radius-from-centre, so the bias is
 * offset by `−sphereRadiusScene`: the displaced surface lands at the true
 * radius regardless of the base sphere's size (these bodies skip triaxial
 * flattening, letting the DEM carry the whole shape). Returns the texture for
 * later disposal, or `null` on fetch failure.
 */
export async function attachDisplacementMap(
	material: MeshStandardMaterial,
	dispMeta: DisplacementMeta,
	tier: string,
	textureLoader: TextureLoader,
	sphereRadiusScene: number
): Promise<Texture | null> {
	const url = versionedUrl(`/v1/textures/${dispMeta.id}/${tier}.webp`, 'textures');
	let texture: Texture;
	try {
		texture = await new Promise<Texture>((resolve, reject) => {
			textureLoader.load(url, resolve, undefined, reject);
		});
	} catch (err) {
		console.warn(`Failed to load displacement map ${url}:`, err);
		return null;
	}

	texture.colorSpace = NoColorSpace;
	material.displacementMap = texture;
	material.displacementScale = kmToScene(dispMeta.scale_km);
	material.displacementBias =
		kmToScene(dispMeta.bias_km) - (dispMeta.absolute_radius ? sphereRadiusScene : 0);
	material.needsUpdate = true;
	return texture;
}

/**
 * Release the texture and reset the material's displacement slots to inert
 * defaults (scale 1, bias 0); three.js drops the vertex chunk once the map is null.
 */
export function disposeDisplacementFromMaterial(material: MeshStandardMaterial): void {
	if (!material.displacementMap) return;
	material.displacementMap.dispose();
	material.displacementMap = null;
	material.displacementScale = 1;
	material.displacementBias = 0;
	material.needsUpdate = true;
}
