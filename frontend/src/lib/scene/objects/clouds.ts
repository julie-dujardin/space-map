/**
 * Cloud-overlay layer parented to a body's mesh. A second sphere, slightly
 * larger than the surface, drawn with a transparent MeshStandardMaterial
 * whose `map` carries the cloud RGBA (alpha = cloud mask). Lit by the same
 * scene lights as the planet, so terminator + dayside shading come for free.
 *
 * Texture tiers mirror the surface tiers (low/medium/high) and are upgraded
 * alongside the surface by the renderer's per-frame LOD pass.
 */
import {
	Mesh,
	MeshStandardMaterial,
	SphereGeometry,
	type Texture,
	type TextureLoader
} from 'three';

import { DATA_BASE } from '$lib/fetch/data-base';
import { jdToDate } from '$lib/format/date';

/** Per-body cloud-overlay metadata — matches `clouds_block` in export/systems.py. */
export interface CloudMeta {
	id: string;
	tiers: string[];
	/** Sortable `YYYYMMDDHH` snapshot ids, ascending. Empty means no snapshots are available. */
	frames: string[];
	source: string;
	organisation: string;
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
	textureTier?: string;
	textureFrame?: string;
	textureLoading?: boolean;
}

/**
 * Offset above the surface (multiplicative on the parent's flattened scale).
 * Small enough to be visually indistinguishable; large enough to avoid the
 * coplanar-fragment depth-equality glitch on some GPUs.
 */
const CLOUD_RADIUS_OFFSET = 1.002;

function cloudTextureUrl(id: string, tier: string, frame: string): string {
	return `${DATA_BASE}/v1/textures/${id}/${tier}_${frame}.webp`;
}

async function fetchCloudTexture(
	id: string,
	tier: string,
	frame: string,
	loader: TextureLoader
): Promise<Texture | null> {
	try {
		return await new Promise<Texture>((resolve, reject) => {
			loader.load(cloudTextureUrl(id, tier, frame), resolve, undefined, reject);
		});
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

/**
 * Pick a snapshot for `jd`. `frames` is assumed pre-sorted ascending (export
 * guarantees this); returns undefined when no snapshots are available.
 *
 * In range: closest snapshot by absolute wall-clock distance. Outside the
 * dataset's range we fall back to the same hour-of-day (rounded to the
 * exported 3h cadence) on the most-recent date (if jd is past the last
 * snapshot) or the oldest date (if it's before the first). It's not perfect
 * — clouds aren't periodic — but it keeps the diurnal character roughly
 * right instead of pinning the entire scene to whatever frame happens to
 * sit at the data boundary.
 */
export function cloudFrameForJd(jd: number, frames: string[]): string | undefined {
	if (frames.length === 0) return undefined;
	const target = jdToDate(jd).getTime();
	const firstMs = frameIdToMs(frames[0]);
	const lastMs = frameIdToMs(frames[frames.length - 1]);

	if (target >= firstMs && target <= lastMs) {
		// Binary search for the first frame at or after target — comparing
		// strings is sufficient because YYYYMMDDHH sorts identically to its
		// wall time.
		let lo = 0;
		let hi = frames.length;
		while (lo < hi) {
			const mid = (lo + hi) >>> 1;
			if (frameIdToMs(frames[mid]) < target) lo = mid + 1;
			else hi = mid;
		}
		if (lo === 0) return frames[0];
		if (lo === frames.length) return frames[frames.length - 1];
		const before = frames[lo - 1];
		const after = frames[lo];
		return target - frameIdToMs(before) <= frameIdToMs(after) - target ? before : after;
	}

	// Outside the dataset — pick the slot matching the sim hour-of-day. The
	// `% 24` handles the wrap when sim hour rounds up past 21 (e.g. 23 → 24
	// → slot 00, which is closer than 21).
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
 * snapshot for `frame`, and return the node. The cloud mesh inherits
 * `parentMesh`'s scale (triaxial flattening) and quaternion (IAU orientation +
 * spin), so it tracks the planet for free. Returns null if there are no
 * frames in the bundle or the texture load fails.
 */
export async function loadCloudNode(
	parentMesh: Mesh,
	parentRadiusScene: number,
	meta: CloudMeta,
	frame: string,
	loader: TextureLoader
): Promise<CloudNode | null> {
	const texture = await fetchCloudTexture(meta.id, 'low', frame, loader);
	if (!texture) return null;

	const material = new MeshStandardMaterial({
		map: texture,
		transparent: true,
		depthWrite: false
	});
	const geometry = new SphereGeometry(parentRadiusScene, 64, 64);
	const mesh = new Mesh(geometry, material);
	// Slightly inflate over the surface; combined with depthWrite=false this
	// avoids z-fighting without visibly puffing the sphere outward.
	mesh.scale.setScalar(CLOUD_RADIUS_OFFSET);
	// Draw after the opaque planet so transparent alpha composites correctly.
	mesh.renderOrder = 1;
	parentMesh.add(mesh);

	return {
		mesh,
		material,
		id: meta.id,
		availableTiers: meta.tiers,
		availableFrames: meta.frames,
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
	frame: string,
	loader: TextureLoader
): Promise<void> {
	if (node.textureLoading) return;
	if (node.textureTier === tier && node.textureFrame === frame) return;
	if (!node.availableTiers.includes(tier)) return;
	if (!node.availableFrames.includes(frame)) return;
	node.textureLoading = true;
	try {
		const texture = await fetchCloudTexture(node.id, tier, frame, loader);
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
