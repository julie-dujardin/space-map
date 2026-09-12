/**
 * Cloud-overlay layer parented to a body's mesh: a slightly larger sphere with
 * a transparent MeshStandardMaterial whose `map` carries cloud RGBA (alpha =
 * mask). Lit by the same scene lights, so terminator/dayside shading is free.
 */
import { Mesh, MeshStandardMaterial, SphereGeometry, SRGBColorSpace, Texture } from 'three';

import { versionedUrl } from '$lib/fetch/data-base';
import { jdToDate } from '$lib/time/jd';

/**
 * Runs of real coverage as `[firstSlot, lastSlot]` ids. Between two runs the
 * upstream published nothing, so no frame is valid there.
 */
export type CloudCoverage = [string, string][];

/** Per-body cloud-overlay metadata — matches `clouds_block` in export/systems.py. */
export interface CloudMeta {
	id: string;
	tiers: string[];
	/** Sortable `YYYYMMDDHH` ids, ascending — only snapshots that differ from the one
	 *  before, so each is the start of the span it covers. Empty means none are available. */
	frames: string[];
	coverage?: CloudCoverage;
	source: string;
	organisation: string;
	license?: string;
	type: string;
	attribution?: string;
	description?: string;
}

export interface CloudNode {
	mesh: Mesh;
	material: MeshStandardMaterial;
	/** Export bundle id (e.g. `naif-399_clouds`) — base path for tier URLs. */
	id: string;
	availableTiers: string[];
	availableFrames: string[];
	availableCoverage?: CloudCoverage;
	textureTier?: string;
	textureFrame?: string;
	textureLoading?: boolean;
	lastSwapMs?: number;
}

/** Offset above the surface (multiplicative on parent scale): small enough to be invisible, large enough to avoid coplanar depth-fighting. Deck bodies (Venus) sit their overlay on the shell's reference level instead. */
export const CLOUD_RADIUS_OFFSET = 1.002;

/** Min interval between cloud-texture swaps. At high time-warp, a new 3h snapshot every render would cost fetch+decode+upload each frame. */
const CLOUD_SWAP_MIN_INTERVAL_MS = 1000;

function cloudTextureUrl(id: string, tier: string, frame: string): string {
	return versionedUrl(`/v1/textures/${id}/${tier}_${frame}.webp`, 'textures');
}

/**
 * Decode off-thread via `createImageBitmap`; `TextureLoader`'s `<img>` decode
 * visibly froze the renderer at high time-warp. Pre-flipping the bitmap lets
 * `texture.flipY = false` skip the UNPACK_FLIP_Y copy at upload.
 */
async function fetchCloudTexture(id: string, tier: string, frame: string): Promise<Texture | null> {
	try {
		const response = await fetch(cloudTextureUrl(id, tier, frame));
		if (!response.ok) {
			throw new Error(`HTTP ${response.status}`);
		}
		const blob = await response.blob();
		const bitmap = await createImageBitmap(blob, { imageOrientation: 'flipY' });
		const texture = new Texture(bitmap);
		texture.flipY = false;
		texture.colorSpace = SRGBColorSpace;
		texture.needsUpdate = true;
		return texture;
	} catch (err) {
		console.warn(`Failed to load ${tier} cloud texture for ${id} @ ${frame}:`, err);
		return null;
	}
}

/** `YYYYMMDDHH` → Unix epoch ms (UTC). Frame ids are zero-padded. */
function frameIdToMs(frameId: string): number {
	const year = parseInt(frameId.slice(0, 4), 10);
	const month = parseInt(frameId.slice(4, 6), 10) - 1;
	const day = parseInt(frameId.slice(6, 8), 10);
	const hour = parseInt(frameId.slice(8, 10), 10);
	return Date.UTC(year, month, day, hour);
}

/** One upstream slot; the last frame of a coverage run holds for this long. Matches `CLOUDS_SLOT_HOURS`. */
const CLOUD_SLOT_MS = 3 * 60 * 60 * 1000;

/** Is `target` inside a run of real coverage? Without `coverage` (older export), the frame span stands in. */
function withinCoverage(target: number, frames: string[], coverage?: CloudCoverage): boolean {
	if (!coverage) {
		return target >= frameIdToMs(frames[0]) && target <= frameIdToMs(frames[frames.length - 1]);
	}
	return coverage.some(
		([from, to]) => target >= frameIdToMs(from) && target < frameIdToMs(to) + CLOUD_SLOT_MS
	);
}

/**
 * Pick a snapshot for `jd` (`frames` pre-sorted ascending).
 *
 * A frame holds until the next one is published, so in covered time the answer
 * is the last frame at or before `jd` — never the next one early, however long
 * the upstream stood still. Outside coverage there is no data: matching the
 * sim's hour-of-day keeps diurnal character instead of pinning the scene to
 * whatever frame sits at the boundary.
 */
export function cloudFrameForJd(
	jd: number,
	frames: string[],
	coverage?: CloudCoverage
): string | undefined {
	if (frames.length === 0) return undefined;
	const target = jdToDate(jd).getTime();
	const firstMs = frameIdToMs(frames[0]);

	if (withinCoverage(target, frames, coverage)) {
		// Binary search for the first frame after target, then step back to the
		// one holding over it; YYYYMMDDHH sorts identically to wall time.
		let lo = 0;
		let hi = frames.length;
		while (lo < hi) {
			const mid = (lo + hi) >>> 1;
			if (frameIdToMs(frames[mid]) <= target) lo = mid + 1;
			else hi = mid;
		}
		return frames[Math.max(0, lo - 1)];
	}

	// Outside the dataset — match the sim hour-of-day. `% 24` handles the wrap
	// when the sim hour rounds up past 21 (23 → 24 → slot 00).
	const simHour = jdToDate(jd).getUTCHours();
	const slotHour = (Math.round(simHour / 3) * 3) % 24;
	const slotHourStr = String(slotHour).padStart(2, '0');
	const matching = frames.filter((f) => f.slice(8, 10) === slotHourStr);
	if (matching.length === 0) {
		// No frame at that hour anywhere — fall back to the closer boundary.
		return target < firstMs ? frames[0] : frames[frames.length - 1];
	}
	return target < firstMs ? matching[0] : matching[matching.length - 1];
}

/**
 * Build the cloud sphere as a child of `parentMesh`, load its `low`-tier
 * snapshot for `frame`. Inherits the parent's scale/quaternion so it tracks
 * the planet for free. `radiusRatio` places it over the surface. Returns null
 * on load failure.
 */
export async function loadCloudNode(
	parentMesh: Mesh,
	parentRadiusScene: number,
	meta: CloudMeta,
	frame: string,
	radiusRatio = CLOUD_RADIUS_OFFSET
): Promise<CloudNode | null> {
	const texture = await fetchCloudTexture(meta.id, 'low', frame);
	if (!texture) return null;

	const material = new MeshStandardMaterial({
		map: texture,
		transparent: true,
		depthWrite: false
	});
	const geometry = new SphereGeometry(parentRadiusScene, 64, 64);
	const mesh = new Mesh(geometry, material);
	// Inflate over the surface; combined with depthWrite=false this avoids
	// z-fighting without visibly puffing the sphere outward.
	mesh.scale.setScalar(radiusRatio);
	// Draw after the opaque planet so transparent alpha composites correctly.
	mesh.renderOrder = 1;
	parentMesh.add(mesh);

	return {
		mesh,
		material,
		id: meta.id,
		availableTiers: meta.tiers,
		availableFrames: meta.frames,
		availableCoverage: meta.coverage,
		textureTier: 'low',
		textureFrame: frame
	};
}

/**
 * Swap the cloud texture to `(tier, frame)`. No-op when already at that pair,
 * when a load is in flight, or when the tier/frame isn't available.
 */
export async function loadCloudTexture(
	node: CloudNode,
	tier: string,
	frame: string
): Promise<void> {
	if (node.textureLoading) return;
	if (node.textureTier === tier && node.textureFrame === frame) return;
	if (!node.availableTiers.includes(tier)) return;
	if (!node.availableFrames.includes(frame)) return;
	const now = performance.now();
	if (node.lastSwapMs !== undefined && now - node.lastSwapMs < CLOUD_SWAP_MIN_INTERVAL_MS) return;
	node.lastSwapMs = now;
	node.textureLoading = true;
	try {
		const texture = await fetchCloudTexture(node.id, tier, frame);
		if (texture) {
			node.material.map?.dispose();
			node.material.map = texture;
			node.material.needsUpdate = true;
			node.textureTier = tier;
			node.textureFrame = frame;
		}
	} finally {
		node.textureLoading = false;
	}
}

/** Dispose all GPU resources owned by a cloud node and detach from its parent. */
export function disposeCloudNode(node: CloudNode): void {
	node.mesh.geometry.dispose();
	node.material.map?.dispose();
	node.material.dispose();
	node.mesh.parent?.remove(node.mesh);
}
