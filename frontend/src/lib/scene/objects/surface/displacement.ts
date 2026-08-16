import {
	DataTexture,
	LinearFilter,
	type MeshStandardMaterial,
	NoColorSpace,
	RedFormat,
	type Texture,
	type TextureLoader,
	UnsignedByteType
} from 'three';
import { versionedUrl } from '$lib/fetch/data-base';
import { kmToScene } from '$lib/math/units';
import { attachSelfShadowToBody } from './self-shadow';
import type { BodyObjects } from '$lib/scene/types';

/**
 * Per-body displacement metadata. `scale_km`/`bias_km` map each texel to
 * `km = bias_km + scale_km * texel`. When `absolute_radius`, that value is
 * radius-from-centre, not elevation — see {@link attachDisplacementMap}.
 */
export interface DisplacementMeta {
	id: string;
	tiers: string[];
	scale_km: number;
	bias_km: number;
	absolute_radius: boolean;
	source: string;
	organisation: string;
	license?: string;
	type: string;
	attribution?: string;
	description?: string;
}

/**
 * Load a body's height map as a displacement map at true scale, shared by the
 * main scene and the lineup. Scale/bias land in the base sphere's own units
 * via `kmToLocal` (scene units/km, or `1/radiusKm` for the lineup's unit
 * sphere), so LOD geometry swaps displace correctly at every tessellation
 * level. `NoColorSpace`: linear height data, not colour.
 *
 * For `absolute_radius` grids the bias is offset by `−sphereRadius` so the
 * displaced surface lands at the true radius regardless of base sphere size
 * (these bodies skip triaxial flattening; the DEM carries the whole shape).
 */
export async function attachDisplacementMap(
	material: MeshStandardMaterial,
	dispMeta: DisplacementMeta,
	tier: string,
	textureLoader: TextureLoader,
	sphereRadius: number,
	kmToLocal: number = kmToScene(1)
): Promise<Texture | null> {
	const url = displacementTierUrl(dispMeta, tier);
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

export function displacementTierUrl(dispMeta: DisplacementMeta, tier: string): string {
	return versionedUrl(`/v1/textures/${dispMeta.id}/${tier}.webp`, 'textures');
}

export async function fetchHeightBitmap(url: string): Promise<ImageBitmap | null> {
	try {
		const response = await fetch(url);
		if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
		return await createImageBitmap(await response.blob());
	} catch (err) {
		console.warn(`Failed to decode displacement map ${url}:`, err);
		return null;
	}
}

/** ~16 MB of RGBA per getImageData call — full-size readback of a 16k map
 *  would exceed browser canvas-area caps (and block the main thread in one go). */
const STRIP_PX = 4_000_000;

/** R-channel rows `[y0..y1]`, read in strips with a yield between so large
 *  tiers don't freeze the frame loop. Hidden tabs skip yields: no frame to
 *  protect, and timer throttling would stretch a 16k decode to tens of minutes. */
export async function readHeightRows(
	bitmap: ImageBitmap,
	y0: number,
	y1: number
): Promise<Uint8Array | null> {
	const w = bitmap.width;
	const stripH = Math.max(1, Math.floor(STRIP_PX / w));
	const canvas = document.createElement('canvas');
	canvas.width = w;
	canvas.height = Math.min(stripH, y1 - y0 + 1);
	const ctx = canvas.getContext('2d', { willReadFrequently: true });
	if (!ctx) return null;
	const out = new Uint8Array(w * (y1 - y0 + 1));
	for (let y = y0; y <= y1; y += stripH) {
		const hh = Math.min(stripH, y1 - y + 1);
		ctx.drawImage(bitmap, 0, y, w, hh, 0, 0, w, hh);
		const px = ctx.getImageData(0, 0, w, hh).data;
		const base = (y - y0) * w;
		for (let i = 0; i < w * hh; i++) out[base + i] = px[i * 4];
		if (!document.hidden && y + stripH <= y1) await new Promise((r) => setTimeout(r));
	}
	return out;
}

/**
 * Swap the body's displacement map to another tier, re-pointing the
 * self-shadow march at the same texture. Uploaded as single-channel R8: a 16k
 * RGBA upload with mips would be ~700 MB VRAM vs ~134 MB, and the shaders
 * only read `.r`/`.x`.
 */
export async function swapDisplacementTier(bo: BodyObjects, tier: string): Promise<void> {
	const meta = bo.displacementMeta;
	if (!meta || !bo.mesh || bo.displacementLoading || bo.displacementTier === tier) return;
	bo.displacementLoading = true;
	try {
		const url = displacementTierUrl(meta, tier);
		const bitmap = await fetchHeightBitmap(url);
		if (!bitmap) return;
		const w = bitmap.width;
		const h = bitmap.height;
		const rows = await readHeightRows(bitmap, 0, h - 1);
		bitmap.close();
		if (!rows) return;
		// Unloaded while decoding — don't re-attach a texture nobody owns.
		if (!bo.mesh || !bo.displacementMap) return;
		// Flip rows in place (DataTexture buffers ignore flipY; v=1 must stay
		// north) — a second full-size buffer would double the 16k tier's 134 MB.
		const tmp = new Uint8Array(w);
		for (let y = 0; y < h >> 1; y++) {
			const top = rows.subarray(y * w, (y + 1) * w);
			const bottom = rows.subarray((h - 1 - y) * w, (h - y) * w);
			tmp.set(top);
			top.set(bottom);
			bottom.set(tmp);
		}
		const tex = new DataTexture(rows, w, h, RedFormat, UnsignedByteType);
		tex.colorSpace = NoColorSpace;
		tex.magFilter = LinearFilter;
		tex.minFilter = LinearFilter;
		tex.generateMipmaps = false;
		// Odd widths (16383, the WebP limit) break the default 4-byte row alignment.
		tex.unpackAlignment = 1;
		tex.needsUpdate = true;
		const material = bo.mesh.material as MeshStandardMaterial;
		const old = material.displacementMap;
		material.displacementMap = tex; // scale/bias unchanged — same metadata
		bo.displacementMap = tex;
		bo.displacementTier = tier;
		if (bo.selfShadow) attachSelfShadowToBody(material, tex, kmToScene(meta.scale_km));
		if (old && old !== tex) old.dispose();
	} finally {
		bo.displacementLoading = false;
	}
}

/**
 * Bilinear texel of a single-channel height map at `(fx, fy)`, matching the
 * GPU's sampling: wrap S, clamp T. `data` may be a row window with its own
 * height and re-based `fy`; a ±1-row margin keeps clamping equivalent to the full map.
 */
export function bilinearHeightTexel(
	data: Uint8Array | Uint8ClampedArray,
	w: number,
	h: number,
	fx: number,
	fy: number
): number {
	const x0 = Math.floor(fx);
	const y0 = Math.floor(fy);
	const tx = fx - x0;
	const ty = fy - y0;
	const wrapCol = (x: number) => ((x % w) + w) % w;
	const clampRow = (y: number) => (y < 0 ? 0 : y > h - 1 ? h - 1 : y);
	const c0 = wrapCol(x0);
	const c1 = wrapCol(x0 + 1);
	const r0 = clampRow(y0) * w;
	const r1 = clampRow(y0 + 1) * w;
	const top = data[r0 + c0] * (1 - tx) + data[r0 + c1] * tx;
	const bot = data[r1 + c0] * (1 - tx) + data[r1 + c1] * tx;
	return (top * (1 - ty) + bot * ty) / 255;
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
