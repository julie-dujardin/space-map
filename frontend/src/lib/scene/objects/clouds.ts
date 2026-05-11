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

/** Per-body cloud-overlay metadata — matches `clouds_block` in export/systems.py. */
export interface CloudMeta {
	id: string;
	tiers: string[];
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
	textureTier?: string;
	textureLoading?: boolean;
}

/**
 * Offset above the surface (multiplicative on the parent's flattened scale).
 * Small enough to be visually indistinguishable; large enough to avoid the
 * coplanar-fragment depth-equality glitch on some GPUs.
 */
const CLOUD_RADIUS_OFFSET = 1.002;

function cloudTextureUrl(id: string, tier: string): string {
	return `${DATA_BASE}/v1/textures/${id}/${tier}.webp`;
}

async function fetchCloudTexture(
	id: string,
	tier: string,
	loader: TextureLoader
): Promise<Texture | null> {
	try {
		return await new Promise<Texture>((resolve, reject) => {
			loader.load(cloudTextureUrl(id, tier), resolve, undefined, reject);
		});
	} catch (err) {
		console.warn(`Failed to load ${tier} cloud texture for ${id}:`, err);
		return null;
	}
}

/**
 * Build the cloud sphere as a child of `parentMesh`, load its `low` tier, and
 * return the node. The cloud mesh inherits `parentMesh`'s scale (triaxial
 * flattening) and quaternion (IAU orientation + spin), so it tracks the
 * planet for free. Returns null if the texture load fails.
 */
export async function loadCloudNode(
	parentMesh: Mesh,
	parentRadiusScene: number,
	meta: CloudMeta,
	loader: TextureLoader
): Promise<CloudNode | null> {
	const texture = await fetchCloudTexture(meta.id, 'low', loader);
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
		textureTier: 'low'
	};
}

/**
 * Swap the cloud texture to `tier`. No-op when already at that tier, when a
 * load is in flight, or when the tier isn't available.
 */
export async function loadCloudTier(
	node: CloudNode,
	tier: string,
	loader: TextureLoader
): Promise<void> {
	if (node.textureLoading) return;
	if (node.textureTier === tier) return;
	if (!node.availableTiers.includes(tier)) return;
	node.textureLoading = true;
	try {
		const texture = await fetchCloudTexture(node.id, tier, loader);
		if (texture) {
			node.material.map?.dispose();
			node.material.map = texture;
			node.material.needsUpdate = true;
			node.textureTier = tier;
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
