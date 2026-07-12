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
	license?: string;
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

/** R-channel rows `[y0..y1]` (top-down), read in full-width strips with a
 *  yield between them so large tiers don't freeze the frame loop. Hidden tabs
 *  skip the yields: there's no frame to protect, and background timer
 *  throttling would stretch a 16k decode to tens of minutes. */
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
 * Swap the body's displacement map to another tier, re-pointing the self-shadow
 * march at the same texture. Uploaded as single-channel R8 (a 16k RGBA upload
 * with mips would be ~700 MB of VRAM; R8 without mips is ~134 MB — and the
 * displacement/self-shadow shaders only ever read `.r`/`.x`).
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
 * Per-feature radial offsets (scene units) so surface labels and landed probes
 * sit on the displaced terrain, not the base sphere. `tier` must match the map
 * the GPU displaces with. Offsets match {@link attachDisplacementMap}'s
 * scale/bias; null on fetch/decode failure.
 */
export async function sampleDisplacementOffsets(
	dispMeta: DisplacementMeta,
	points: { latRad: number; lonRad: number }[],
	sphereRadiusScene: number,
	tier = 'low'
): Promise<Float32Array | null> {
	const url = displacementTierUrl(dispMeta, tier);
	const bitmap = await fetchHeightBitmap(url);
	if (!bitmap) return null;
	const w = bitmap.width;
	const h = bitmap.height;

	// Texel coordinates per point, and the row window covering them all (+1 row
	// of bilinear margin). Only that window is read back — clustered points
	// (probe cell corners) cost a few rows even on the 16k tier.
	const fxs = new Float64Array(points.length);
	const fys = new Float64Array(points.length);
	let rowLo = h - 1;
	let rowHi = 0;
	for (let i = 0; i < points.length; i++) {
		const u = 0.5 + points[i].lonRad / (2 * Math.PI);
		const v = 0.5 + points[i].latRad / Math.PI;
		fxs[i] = (u - Math.floor(u)) * w - 0.5; // lon east-positive 0..2π wraps
		fys[i] = (1 - v) * h - 0.5;
		const y0 = Math.floor(fys[i]);
		rowLo = Math.min(rowLo, Math.max(0, y0));
		rowHi = Math.max(rowHi, Math.min(h - 1, y0 + 1));
	}
	const rows = await readHeightRows(bitmap, rowLo, rowHi);
	bitmap.close();
	if (!rows) {
		console.warn(`Failed to sample displacement map ${url}: no 2D context`);
		return null;
	}

	const scale = kmToScene(dispMeta.scale_km);
	const bias = kmToScene(dispMeta.bias_km) - (dispMeta.absolute_radius ? sphereRadiusScene : 0);
	const out = new Float32Array(points.length);
	// Bilinear, matching the GPU's displacement sampling (wrap S, clamp T), so a
	// probe/label lands on the rendered surface and not up to a quantisation step
	// off it — the 8-bit map's levels are ~scale_km/255 apart.
	const wrapCol = (x: number) => ((x % w) + w) % w;
	const clampRow = (y: number) => (y < rowLo ? rowLo : y > rowHi ? rowHi : y);
	for (let i = 0; i < points.length; i++) {
		const x0 = Math.floor(fxs[i]);
		const y0 = Math.floor(fys[i]);
		const tx = fxs[i] - x0;
		const ty = fys[i] - y0;
		const c0 = wrapCol(x0);
		const c1 = wrapCol(x0 + 1);
		const r0 = (clampRow(y0) - rowLo) * w;
		const r1 = (clampRow(y0 + 1) - rowLo) * w;
		const top = rows[r0 + c0] * (1 - tx) + rows[r0 + c1] * tx;
		const bot = rows[r1 + c0] * (1 - tx) + rows[r1 + c1] * tx;
		const texel = (top * (1 - ty) + bot * ty) / 255;
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
