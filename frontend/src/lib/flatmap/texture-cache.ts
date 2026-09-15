/**
 * The decoded map pictures, shared by every flat map on the page.
 *
 * A surface texture costs tens to hundreds of megabytes as pixels. A 16k-wide
 * map is half a gigabyte. The same body is often on screen more than once. A
 * gallery of traverses is a dozen maps of four bodies. One copy for each map
 * fills the memory of a phone.
 *
 * This store keeps one copy of each picture, and one copy of the readable
 * version the resampler samples. A picture stays while a map claims it.
 * Unclaimed pictures are dropped, oldest first, when they go past the budget.
 */

import { imageToRaster, type RasterImage } from './raster';

/** The memory a picture uses, in bytes. */
function bitmapBytes(width: number, height: number): number {
	return width * height * 4;
}

/**
 * How much unclaimed picture is kept, in bytes.
 *
 * A picture a map draws is always kept, whatever its size. Only the pictures
 * no map asks for count against the budget. `deviceMemory` gives the memory of
 * the machine in gigabytes. Some browsers do not report it. A middle value is
 * used for those.
 */
function budgetBytes(): number {
	const gigabytes = (navigator as { deviceMemory?: number }).deviceMemory ?? 4;
	return Math.max(1, Math.min(gigabytes, 8)) * 24 * 1024 * 1024;
}

interface Entry<T> {
	value: T;
	bytes: number;
	claims: number;
	/** Counter of the last claim. The lowest value is dropped first. */
	used: number;
}

/** The pictures of one kind, by the key that was asked for. */
class Store<T> {
	private readonly entries = new Map<string, Entry<T>>();
	private clock = 0;

	constructor(private readonly free: (value: T) => void) {}

	/** Claim a picture that is already held. Each map that draws it holds one
	 *  claim. */
	claim(key: string): T | null {
		const entry = this.entries.get(key);
		if (!entry) return null;
		entry.claims++;
		entry.used = ++this.clock;
		return entry.value;
	}

	put(key: string, value: T, bytes: number): T {
		const existing = this.entries.get(key);
		if (existing) {
			// Two maps can decode the same picture at the same time. The store
			// keeps one copy and drops the other. They are one object when both
			// maps waited on the same decode, and that one must stay open.
			if (existing.value !== value) this.free(value);
			existing.claims++;
			existing.used = ++this.clock;
			return existing.value;
		}
		this.entries.set(key, { value, bytes, claims: 1, used: ++this.clock });
		this.evict();
		return value;
	}

	release(key: string): void {
		const entry = this.entries.get(key);
		if (!entry) return;
		entry.claims = Math.max(0, entry.claims - 1);
		this.evict();
	}

	/** Drop unclaimed pictures, oldest first, until they fit the budget. */
	private evict(): void {
		let unclaimed = 0;
		for (const entry of this.entries.values()) if (!entry.claims) unclaimed += entry.bytes;
		const budget = budgetBytes();
		if (unclaimed <= budget) return;
		const order = [...this.entries]
			.filter(([, entry]) => !entry.claims)
			.sort((a, b) => a[1].used - b[1].used);
		for (const [key, entry] of order) {
			if (unclaimed <= budget) return;
			this.entries.delete(key);
			this.free(entry.value);
			unclaimed -= entry.bytes;
		}
	}

	/** @internal For tests. Drops every picture, claimed or not. */
	clear(): void {
		for (const entry of this.entries.values()) this.free(entry.value);
		this.entries.clear();
	}
}

const bitmaps = new Store<ImageBitmap>((bitmap) => bitmap.close());
const rasters = new Store<RasterImage>(() => {});
/** The decodes in progress. A dozen maps of one body fetch it one time. */
const pending = new Map<string, Promise<ImageBitmap | null>>();

/** The key a picture is filed under. The width is part of it. A map that
 *  resamples asks for a smaller picture than one that draws it directly. */
export function textureKey(url: string, decodeWidth: number | null): string {
	return decodeWidth ? `${url}@${decodeWidth}` : url;
}

/**
 * Fetch and decode a picture, or claim the copy that is already decoded.
 *
 * `decodeWidth` makes the picture smaller as it is decoded. Use it for a map
 * that cannot sample more than that width. Null keeps the picture whole.
 *
 * The caller holds one claim. It must call {@link releaseBitmap} with the same
 * key when it stops drawing the picture.
 */
export async function acquireBitmap(
	url: string,
	decodeWidth: number | null
): Promise<{ key: string; bitmap: ImageBitmap } | null> {
	const key = textureKey(url, decodeWidth);
	const held = bitmaps.claim(key);
	if (held) return { key, bitmap: held };
	let work = pending.get(key);
	if (!work) {
		work = decode(url, decodeWidth);
		pending.set(key, work);
		work.finally(() => pending.delete(key));
	}
	const bitmap = await work;
	if (!bitmap) return null;
	const kept = bitmaps.put(key, bitmap, bitmapBytes(bitmap.width, bitmap.height));
	return { key, bitmap: kept };
}

/**
 * Fetch a picture and decode it to `decodeWidth`.
 *
 * The decoder does the resize. The full-sized pixels are then never held in
 * memory. Height follows width, so the picture keeps its shape. A browser that
 * does not accept the option gives the whole picture, which also draws.
 */
async function decode(url: string, decodeWidth: number | null): Promise<ImageBitmap | null> {
	const response = await fetch(url);
	if (!response.ok) throw new Error(`HTTP ${response.status}`);
	const blob = await response.blob();
	if (!decodeWidth) return createImageBitmap(blob);
	try {
		return await createImageBitmap(blob, { resizeWidth: decodeWidth, resizeQuality: 'high' });
	} catch {
		return createImageBitmap(blob);
	}
}

export function releaseBitmap(key: string): void {
	bitmaps.release(key);
}

/**
 * The readable copy of a picture at a working width, made one time.
 *
 * A readback costs tens of milliseconds and as much memory as the picture. The
 * maps of one body at one width sample the same copy. The caller holds one
 * claim and must call {@link releaseRaster} with the key.
 */
export function acquireRaster(
	url: string,
	workingWidth: number,
	source: ImageBitmap
): { key: string; raster: RasterImage } | null {
	const key = textureKey(url, workingWidth);
	const held = rasters.claim(key);
	if (held) return { key, raster: held };
	const raster = imageToRaster(source, workingWidth);
	if (!raster) return null;
	return { key, raster: rasters.put(key, raster, bitmapBytes(raster.width, raster.height)) };
}

export function releaseRaster(key: string): void {
	rasters.release(key);
}

/** @internal For tests. */
export function clearTextureCache(): void {
	bitmaps.clear();
	rasters.clear();
	pending.clear();
}
