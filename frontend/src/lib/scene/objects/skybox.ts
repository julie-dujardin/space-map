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
 * Frame alignment: the source EXR (NASA SVS Deep Star Maps 2020) is an
 * equirectangular all-sky map in J2000 *equatorial* coords (poles = celestial
 * poles, center column = RA=0h). py360convert puts RA=0h on the cube's +Z
 * face and the NCP on the +Y face. The renderer's world frame is J2000
 * *ecliptic* with Three.js Y-up (ecliptic X→scene X, ecliptic Z→scene Y).
 *
 * Three.js' background cube shader samples the cubemap as
 * `textureCube(envMap, backgroundRotation * vec3(-w.x, w.y, w.z))` — i.e. the
 * X-flip from the cubemap's left-handed convention is applied *before*
 * `backgroundRotation`. So for a world direction `w`, the texel sampled is
 * `s = R · flip(w)`.
 *
 * The analytical part: anchor the vernal equinox at scene +X to cube +Z and
 * the NCP at scene (0, cos ε, −sin ε) to cube +Y, which gives
 * `Rᵧ(+π/2) · Rₓ(+ε)`. That alone produces a result that's 180° away from
 * what the SVS map actually delivers — Polaris ends up at the SCP, gal-center
 * lands at the anti-center, etc. The cause hasn't been fully isolated (the
 * EXR's row-0=NCP and east=left conventions both check out by direct
 * sampling), but the empirical correction is a 180° rotation about the
 * scene-frame RA=18h axis. Expressed as XYZ Euler it's (−133°, −180°, 0°),
 * verified by aligning Polaris, Sirius, and the Magellanic Clouds to the
 * visible texture features. We compose that empirical post-rotation onto
 * the analytical base.
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
 * Quaternion that rotates the X-flipped world direction into the cubemap
 * sample direction. The composed analytical + empirical rotation reduces to
 * the surprisingly clean XYZ-Euler form `Rₓ(−π/2) · Rᵧ(π/2 − ε) · R_z(−π/2)`
 * — the two ±90° rotations are pure axis swaps, and the only place the
 * obliquity shows up is the middle angle (the complement of ε). Why it comes
 * out this clean despite being derived empirically is the open question
 * called out in the file header.
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
