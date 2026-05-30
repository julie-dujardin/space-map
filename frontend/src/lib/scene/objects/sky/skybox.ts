/**
 * Celestial-sphere skybox (`scene.background`). Cube faces sourced from the
 * NASA SVS Deep Star Maps 2020 EXR (equatorial-frame equirectangular,
 * converted via py360convert). Tier auto-selects from `renderer.capabilities.maxTextureSize`.
 *
 * Frame alignment: the SVS map is in J2000 equatorial coords; the renderer's
 * world frame is J2000 ecliptic. The analytical rotation that maps equinox to
 * scene +X and NCP to scene (0, cos ε, −sin ε) lands 180° away from what the
 * EXR actually delivers — root cause unresolved. Empirical correction is a
 * 180° post-rotation about scene-frame RA=18h, verified against Polaris,
 * Sirius, and the Magellanic Clouds.
 */
import {
	CubeTextureLoader,
	Quaternion,
	SRGBColorSpace,
	Vector3,
	type Scene,
	type WebGLRenderer
} from 'three';

import { DATA_BASE } from '$lib/fetch/data-base';
import { fetchMetadata, type SkyboxMetadata } from '$lib/fetch/metadata';
import { EARTH_OBLIQUITY_DEG } from '$lib/math/units';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';

const DEG2RAD = Math.PI / 180;
const OBLIQUITY_RAD = EARTH_OBLIQUITY_DEG * DEG2RAD;

/**
 * Composed analytical + empirical rotation reduces to
 * `Rₓ(−π/2) · Rᵧ(π/2 − ε) · R_z(−π/2)` — see file header for the empirical part.
 */
export const SKYBOX_BASE_ROTATION = new Quaternion()
	.setFromAxisAngle(new Vector3(0, 0, 1), -Math.PI / 2)
	.premultiply(new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), Math.PI / 2 - OBLIQUITY_RAD))
	.premultiply(new Quaternion().setFromAxisAngle(new Vector3(1, 0, 0), -Math.PI / 2));

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
	// `scene.backgroundRotation` is owned by the renderer (see
	// `SceneRenderer.setSkyboxAdjust`), so we don't write it here to avoid
	// clobbering a user adjustment that may have raced ahead of this async
	// load. The renderer seeds the rotation synchronously at scene-init time.
}

/**
 * Fetch the top-level metadata (memoized; shares the chunk-prefetcher's
 * promise), pick a tier, and install the cubemap-skybox bundle as
 * `scene.background`. Also publishes the bundle's credit fields onto
 * `ctx.credits.skybox` so the in-map attribution popover can surface them.
 * Fire-and-forget from the renderer init path — errors (including a missing
 * skybox block) are swallowed with a console warning so the scene falls back
 * to its default black background instead of breaking.
 */
export async function loadSkybox(
	scene: Scene,
	renderer: WebGLRenderer,
	ctx: ContextManager
): Promise<void> {
	try {
		const meta = await fetchMetadata();
		if (!meta.skybox) return;
		ctx.credits.skybox = {
			source: meta.skybox.source,
			organisation: meta.skybox.organisation,
			attribution: meta.skybox.attribution,
			description: meta.skybox.description
		};
		await loadFromMeta(scene, renderer, meta.skybox);
	} catch (err) {
		console.warn('Failed to load skybox:', err);
	}
}
