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
 * Per-feature radial offsets (scene units) so surface labels sit on the
 * displaced terrain, not the base sphere. Offsets match
 * {@link attachDisplacementMap}'s scale/bias; null on fetch/decode failure.
 */
export async function sampleDisplacementOffsets(
	dispMeta: DisplacementMeta,
	points: { latRad: number; lonRad: number }[],
	sphereRadiusScene: number
): Promise<Float32Array | null> {
	const url = versionedUrl(`/v1/textures/${dispMeta.id}/low.webp`, 'textures');
	let pixels: ImageData;
	let w: number;
	let h: number;
	try {
		const response = await fetch(url);
		if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
		const bitmap = await createImageBitmap(await response.blob());
		w = bitmap.width;
		h = bitmap.height;
		const canvas = document.createElement('canvas');
		canvas.width = w;
		canvas.height = h;
		const ctx = canvas.getContext('2d', { willReadFrequently: true });
		if (!ctx) throw new Error('no 2D context');
		ctx.drawImage(bitmap, 0, 0);
		pixels = ctx.getImageData(0, 0, w, h);
		bitmap.close();
	} catch (err) {
		console.warn(`Failed to sample displacement map ${url}:`, err);
		return null;
	}

	const scale = kmToScene(dispMeta.scale_km);
	const bias = kmToScene(dispMeta.bias_km) - (dispMeta.absolute_radius ? sphereRadiusScene : 0);
	const data = pixels.data;
	const out = new Float32Array(points.length);
	for (let i = 0; i < points.length; i++) {
		const u = 0.5 + points[i].lonRad / (2 * Math.PI);
		const v = 0.5 + points[i].latRad / Math.PI;
		const uw = u - Math.floor(u); // lon is east-positive 0..2π, so u must wrap not clamp
		const col = Math.min(w - 1, Math.floor(uw * w));
		const row = Math.min(h - 1, Math.max(0, Math.floor((1 - v) * h)));
		const texel = data[(row * w + col) * 4] / 255; // height in the R channel
		out[i] = texel * scale + bias;
	}
	return out;
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
