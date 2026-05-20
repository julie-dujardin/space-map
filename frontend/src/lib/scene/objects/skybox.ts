/**
 * Celestial-sphere skybox drawn behind the whole scene as `scene.background`.
 * Six cube faces are loaded as a `CubeTexture` via `CubeTextureLoader`;
 * `scene.background = cube` makes Three.js render the inside of the cube
 * before any object pass, with mip-correct filtering at the edges.
 *
 * The exported bundle is described in `metadata.skybox` (see
 * `lib/fetch/metadata.ts`). Face URLs are
 * `/v1/textures/{skybox.id}/{tier}_{face}.webp`, where face ∈ `skybox.faces`
 * and tier ∈ `skybox.tiers`. Tier selection picks the largest per-face size
 * that fits `renderer.capabilities.maxTextureSize` (typically `high` (4K) on
 * desktop, `low` (2K) on mobile WebGL).
 *
 * The bundle's `frame` is J2000 ICRF. The renderer applies any RA/dec
 * orientation fixup via `scene.backgroundRotation` — leaving it at identity
 * for v1 and tweaking once the scene is visible.
 */
import { CubeTextureLoader, SRGBColorSpace, type Scene, type WebGLRenderer } from 'three';

import { DATA_BASE } from '$lib/fetch/data-base';
import { fetchMetadata, type SkyboxMetadata } from '$lib/fetch/metadata';

/**
 * Three.js' `CubeTextureLoader` expects URLs in this order: positive-X,
 * negative-X, positive-Y, negative-Y, positive-Z, negative-Z. The exporter
 * names files with these exact suffixes (`{tier}_{face}.webp`), so the URL
 * builder just maps over this list.
 */
const FACE_ORDER = ['px', 'nx', 'py', 'ny', 'pz', 'nz'] as const;

/**
 * Pick the largest tier whose per-face edge length is ≤ `maxTextureSize`.
 * Falls back to the smallest tier when even that exceeds the cap (so we
 * still attempt a load on very constrained devices instead of going blank).
 * Returns null only when the bundle declares no tiers.
 */
function pickTier(meta: SkyboxMetadata, maxTextureSize: number): string | null {
	if (meta.tiers.length === 0) return null;
	const ordered = [...meta.tiers].sort(
		(a, b) => (meta.tier_face_size[b] ?? 0) - (meta.tier_face_size[a] ?? 0)
	);
	for (const tier of ordered) {
		if ((meta.tier_face_size[tier] ?? Infinity) <= maxTextureSize) return tier;
	}
	return ordered[ordered.length - 1];
}

function faceUrl(id: string, tier: string, face: string): string {
	return `${DATA_BASE}/v1/textures/${id}/${tier}_${face}.webp`;
}

async function loadFromMeta(
	scene: Scene,
	renderer: WebGLRenderer,
	meta: SkyboxMetadata
): Promise<void> {
	const tier = pickTier(meta, renderer.capabilities.maxTextureSize);
	if (!tier) {
		console.warn(`Skybox ${meta.id}: no tiers declared`);
		return;
	}
	const urls = FACE_ORDER.map((face) => faceUrl(meta.id, tier, face));
	const cube = await new CubeTextureLoader().loadAsync(urls);
	cube.colorSpace = SRGBColorSpace;
	scene.background = cube;
}

/**
 * Fetch the top-level metadata (memoized; shares the chunk-prefetcher's
 * promise), pick a tier, and install the cubemap-skybox bundle as
 * `scene.background`. Fire-and-forget from the renderer init path — errors
 * (including a missing skybox block) are swallowed with a console warning so
 * the scene falls back to its default black background instead of breaking.
 */
export async function loadSkybox(scene: Scene, renderer: WebGLRenderer): Promise<void> {
	try {
		const meta = await fetchMetadata();
		if (!meta.skybox) return;
		await loadFromMeta(scene, renderer, meta.skybox);
	} catch (err) {
		console.warn('Failed to load skybox:', err);
	}
}
