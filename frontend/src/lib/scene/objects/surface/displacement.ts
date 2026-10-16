import {
	type CompressedTextureMipmap,
	DataTexture,
	FloatType,
	LinearFilter,
	LinearMipmapLinearFilter,
	type MeshStandardMaterial,
	NoColorSpace,
	RedFormat,
	type Texture,
	type TextureLoader,
	UnsignedByteType,
	type WebGLRenderer
} from 'three';
import { tileUrl, tilesBase, versionedUrl } from '$lib/fetch/data-base';
import { textureAllowed } from '$lib/host';
import { kmToScene } from '$lib/math/units';
import { loadHeightTile } from '$lib/scene/relief/client';
import { attachSelfShadowToBody } from './self-shadow';
import type { BodyObjects, TextureBundleMeta, TilesBlock } from '$lib/scene/types';

/**
 * Per-body displacement metadata. `scale_km`/`bias_km` map each texel to
 * `km = bias_km + scale_km * texel`. When `absolute_radius`, that value is
 * radius-from-centre, not elevation — see {@link attachDisplacementMap}.
 */
export interface DisplacementMeta extends TextureBundleMeta {
	scale_km: number;
	bias_km: number;
	absolute_radius: boolean;
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
	setDisplacementScale(material, dispMeta, sphereRadius, kmToLocal);
	material.needsUpdate = true;
	return texture;
}

/** Scale and bias that put a texel of `dispMeta`'s map at its true height
 *  over a sphere of `sphereRadius`. */
export function setDisplacementScale(
	material: MeshStandardMaterial,
	dispMeta: DisplacementMeta,
	sphereRadius: number,
	kmToLocal: number = kmToScene(1)
): void {
	material.displacementScale = dispMeta.scale_km * kmToLocal;
	material.displacementBias =
		dispMeta.bias_km * kmToLocal - (dispMeta.absolute_radius ? sphereRadius : 0);
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

/** The tier of a map made from the coarsest level of the body's height pyramid. */
export const PYRAMID_TIER = 'pyramid';

/** Bodies whose pyramid map did not load. They keep the tiers. */
const pyramidFailed = new WeakSet<BodyObjects>();

/**
 * Whether `bo` can take its whole-globe heights from its height pyramid. The
 * pyramid states 16 bits a pixel, and the tiers 8: a step of the tiers is a
 * terrace in the relief of a body with a large range, such as Vesta. The map
 * holds floats, which only some devices filter.
 */
export function pyramidHeightsServe(bo: BodyObjects, renderer: WebGLRenderer): boolean {
	const tiles = bo.displacementMeta?.tiles;
	return (
		!!tiles &&
		tiles.scale_km !== undefined &&
		tilesBase() !== '' &&
		textureAllowed(tiles.distribution) &&
		renderer.extensions.has('OES_texture_float_linear') &&
		!pyramidFailed.has(bo)
	);
}

/**
 * Swap the body's displacement map to another tier, or to `PYRAMID_TIER`, and
 * point the self-shadow at the new map.
 */
export async function swapDisplacementTier(bo: BodyObjects, tier: string): Promise<void> {
	const meta = bo.displacementMeta;
	if (!meta || !bo.mesh || bo.displacementLoading || bo.displacementTier === tier) return;
	bo.displacementLoading = true;
	try {
		const tex = tier === PYRAMID_TIER ? await pyramidMap(bo, meta) : await tierMap(meta, tier);
		if (!tex) return;
		// Unloaded while decoding — don't re-attach a texture nobody owns.
		if (!bo.mesh || !bo.displacementMap) {
			tex.dispose();
			return;
		}
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
 * A tier's map as single-channel R8: a 16k RGBA upload with mips would be
 * ~700 MB of VRAM against ~134 MB, and the shaders only read `.r`/`.x`.
 */
async function tierMap(meta: DisplacementMeta, tier: string): Promise<DataTexture | null> {
	const bitmap = await fetchHeightBitmap(displacementTierUrl(meta, tier));
	if (!bitmap) return null;
	const w = bitmap.width;
	const h = bitmap.height;
	const rows = await readHeightRows(bitmap, 0, h - 1);
	bitmap.close();
	if (!rows) return null;
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
	return tex;
}

async function pyramidMap(bo: BodyObjects, meta: DisplacementMeta): Promise<DataTexture | null> {
	if (!meta.tiles) return null;
	try {
		return await pyramidHeights(meta, meta.tiles);
	} catch (err) {
		console.warn(`Failed to load the height pyramid of ${meta.id}:`, err);
		pyramidFailed.add(bo);
		return null;
	}
}

/**
 * The two tiles of the pyramid's level 0 as one map, in the tiers' coding
 * (`km = bias_km + scale_km · texel`), so that every reader of the tiers
 * reads it unchanged. Its mipmaps are made here: the GPU does not make them
 * for floats on every device.
 */
async function pyramidHeights(meta: DisplacementMeta, tiles: TilesBlock): Promise<DataTexture> {
	const signal = new AbortController().signal;
	const halves = await Promise.all(
		[0, 1].map((x) => loadHeightTile(tileUrl(tiles, '', 0, x, 0), true, signal))
	);
	const size = halves[0].size;
	const width = 2 * size;
	const data = new Float32Array(width * size);
	// The two codings state km in the same frame.
	const gain = (tiles.scale_km ?? 0) / 65535 / meta.scale_km;
	const offset = ((tiles.bias_km ?? 0) - meta.bias_km) / meta.scale_km;
	halves.forEach(({ heights }, x) => {
		for (let row = 0; row < size; row++) {
			const src = row * size;
			const dst = row * width + x * size;
			for (let i = 0; i < size; i++) data[dst + i] = heights[src + i] * gain + offset;
		}
	});
	const tex = new DataTexture(data, width, size, RedFormat, FloatType);
	tex.colorSpace = NoColorSpace;
	tex.magFilter = LinearFilter;
	tex.minFilter = LinearMipmapLinearFilter;
	tex.generateMipmaps = false;
	tex.mipmaps = mipChain(data, width, size);
	tex.needsUpdate = true;
	return tex;
}

/** The map and each halving of it down to one pixel, by the mean of the
 *  pixels each one covers. Sides are powers of two. */
function mipChain(data: Float32Array, width: number, height: number): CompressedTextureMipmap[] {
	const chain = [{ data, width, height }];
	while (width > 1 || height > 1) {
		const w = Math.max(1, width >> 1);
		const h = Math.max(1, height >> 1);
		const sx = width / w;
		const sy = height / h;
		const out = new Float32Array(w * h);
		for (let y = 0; y < h; y++) {
			for (let x = 0; x < w; x++) {
				let sum = 0;
				for (let dy = 0; dy < sy; dy++) {
					const row = (y * sy + dy) * width + x * sx;
					for (let dx = 0; dx < sx; dx++) sum += data[row + dx];
				}
				out[y * w + x] = sum / (sx * sy);
			}
		}
		chain.push({ data: out, width: w, height: h });
		data = out;
		width = w;
		height = h;
	}
	return chain;
}

/**
 * Bilinear texel of a single-channel height map at `(fx, fy)`, matching the
 * GPU's sampling: wrap S, clamp T. Bytes count 255 to the unit, floats are
 * texels as they are. `data` may be a row window with its own height and
 * re-based `fy`; a ±1-row margin keeps clamping equivalent to the full map.
 */
export function bilinearHeightTexel(
	data: Uint8Array | Uint8ClampedArray | Float32Array,
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
	const texel = top * (1 - ty) + bot * ty;
	return data instanceof Float32Array ? texel : texel / 255;
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
