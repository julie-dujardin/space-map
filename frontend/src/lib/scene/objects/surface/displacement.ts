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
 * at true scale, shared by the main scene and the lineup. Scale/bias land in the
 * base sphere's own units via `kmToLocal` (scene units per km for the main scene;
 * the lineup renders on a unit sphere = `radiusKm`, so it passes `1/radiusKm`),
 * so the per-frame sphere-LOD geometry swap displaces correctly at every
 * tessellation level. `NoColorSpace`: it's linear height data, not colour.
 *
 * For `absolute_radius` grids the values are radius-from-centre, so the bias is
 * offset by `−sphereRadius`: the displaced surface lands at the true radius
 * regardless of the base sphere's size (these bodies skip triaxial flattening,
 * letting the DEM carry the whole shape). Returns the texture for later disposal,
 * or `null` on fetch failure.
 */
export async function attachDisplacementMap(
	material: MeshStandardMaterial,
	dispMeta: DisplacementMeta,
	tier: string,
	textureLoader: TextureLoader,
	sphereRadius: number,
	kmToLocal: number = kmToScene(1)
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
	material.displacementScale = dispMeta.scale_km * kmToLocal;
	material.displacementBias =
		dispMeta.bias_km * kmToLocal - (dispMeta.absolute_radius ? sphereRadius : 0);
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
	// Bilinear, matching the GPU's displacement sampling (wrap S, clamp T), so a
	// probe/label lands on the rendered surface and not up to a quantisation step
	// off it — the 8-bit map's levels are ~scale_km/255 apart.
	const wrapCol = (x: number) => ((x % w) + w) % w;
	const clampRow = (y: number) => (y < 0 ? 0 : y > h - 1 ? h - 1 : y);
	for (let i = 0; i < points.length; i++) {
		const u = 0.5 + points[i].lonRad / (2 * Math.PI);
		const v = 0.5 + points[i].latRad / Math.PI;
		const fx = (u - Math.floor(u)) * w - 0.5; // lon east-positive 0..2π wraps
		const fy = (1 - v) * h - 0.5;
		const x0 = Math.floor(fx);
		const y0 = Math.floor(fy);
		const tx = fx - x0;
		const ty = fy - y0;
		const c0 = wrapCol(x0);
		const c1 = wrapCol(x0 + 1);
		const r0 = clampRow(y0) * w;
		const r1 = clampRow(y0 + 1) * w;
		const top = data[(r0 + c0) * 4] * (1 - tx) + data[(r0 + c1) * 4] * tx;
		const bot = data[(r1 + c0) * 4] * (1 - tx) + data[(r1 + c1) * 4] * tx;
		const texel = (top * (1 - ty) + bot * ty) / 255; // height in the R channel
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
