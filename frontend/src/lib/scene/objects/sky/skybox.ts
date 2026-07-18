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
	CubeTexture,
	Quaternion,
	SRGBColorSpace,
	Vector3,
	type Scene,
	type WebGLRenderer
} from 'three';

import { versionedUrl } from '$lib/fetch/data-base';
import { eagerMinorsDone } from '$lib/scene/setup/load-gates';
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
	return versionedUrl(`/v1/textures/${id}/${tier}_${face}.webp`, 'textures');
}

/**
 * Fetch + decode one tier's six faces as ImageBitmaps. Bitmap upload skips the
 * CPU-side convert that `texSubImage2D(HTMLImageElement)` pays (~1s main-thread
 * stall for the 4k tier), and decode happens off-thread in `createImageBitmap`.
 * `imageOrientation: 'none'` matches the `<img>` path's flipY=false upload, so
 * the empirically-calibrated SKYBOX_BASE_ROTATION stays valid.
 */
async function loadTierBitmaps(id: string, tier: string): Promise<ImageBitmap[]> {
	return Promise.all(
		FACE_ORDER.map(async (face) => {
			const res = await fetch(faceUrl(id, tier, face));
			if (!res.ok) throw new Error(`Skybox face fetch failed (${res.status}): ${tier}_${face}`);
			const blob = await res.blob();
			return createImageBitmap(blob, { imageOrientation: 'none', premultiplyAlpha: 'none' });
		})
	);
}

/** Fetch+decode promises, shared so the early prefetch and the install reuse one fetch per tier. */
const tierPrefetch = new Map<string, Promise<ImageBitmap[]>>();

function tierBitmaps(id: string, tier: string): Promise<ImageBitmap[]> {
	let p = tierPrefetch.get(tier);
	if (!p) {
		p = loadTierBitmaps(id, tier);
		tierPrefetch.set(tier, p);
	}
	return p;
}

function makeCube(bitmaps: ImageBitmap[]): CubeTexture {
	const cube = new CubeTexture(bitmaps);
	cube.colorSpace = SRGBColorSpace;
	cube.needsUpdate = true;
	return cube;
}

/** Smallest declared tier, for the fast first paint. */
function pickLowTier(meta: SkyboxMetadata): string | null {
	if (meta.tiers.length === 0) return null;
	return [...meta.tiers].sort(
		(a, b) => (meta.tier_face_size[a] ?? 0) - (meta.tier_face_size[b] ?? 0)
	)[0];
}

/**
 * Start fetching+decoding the low skybox tier as soon as metadata is known,
 * without waiting for the renderer. Low tier only: the full tier is an order of
 * magnitude larger and waits for the eager-minors gate so it doesn't crowd the
 * critical path (see {@link loadFromMeta}).
 */
export function prefetchSkyboxTiers(meta: SkyboxMetadata): void {
	const low = pickLowTier(meta);
	if (low) void tierBitmaps(meta.id, low).catch(() => tierPrefetch.delete(low));
}

/** Full-res tier load waits on the eager point cloud, but never longer than this. */
const FULL_TIER_GATE_TIMEOUT_MS = 12_000;

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
	// `scene.backgroundRotation` is owned by the renderer (see
	// `SceneRenderer.setSkyboxAdjust`), so we don't write it here to avoid
	// clobbering a user adjustment that may have raced ahead of this async
	// load. The renderer seeds the rotation synchronously at scene-init time.
	const lowTier = pickLowTier(meta);
	// Holder object: the low cube is assigned from an async race the TS
	// control-flow analysis can't narrow through a plain `let`.
	const lowRef: { cube: CubeTexture | null } = { cube: null };
	let fullInstalled = false;
	if (lowTier && lowTier !== tier) {
		// Don't gate the full tier behind the low tier: install low only if it
		// wins the race, so a preloaded/cached full tier goes straight up.
		void tierBitmaps(meta.id, lowTier)
			.then((bitmaps) => {
				if (fullInstalled) return;
				lowRef.cube = makeCube(bitmaps);
				scene.background = lowRef.cube;
				performance.mark('sm-skybox-low');
			})
			.catch(() => {});
	}
	// Full tier is large (≈11MB) — hold it until the eager minor wave has the
	// bandwidth it needs. Bounded by a timeout so a stalled/failed load can't
	// strand the background on the low tier forever.
	await Promise.race([
		eagerMinorsDone,
		new Promise<void>((resolve) => setTimeout(resolve, FULL_TIER_GATE_TIMEOUT_MS))
	]);
	const full = makeCube(await tierBitmaps(meta.id, tier));
	// Upload during idle time rather than mid-frame: initTexture pushes the
	// six faces to the GPU now, so the first render that samples the cube
	// doesn't absorb the upload cost.
	await new Promise<void>((resolve) =>
		'requestIdleCallback' in window
			? requestIdleCallback(() => resolve(), { timeout: 2000 })
			: setTimeout(resolve, 500)
	);
	renderer.initTexture(full);
	fullInstalled = true;
	scene.background = full;
	performance.mark('sm-skybox-high');
	lowRef.cube?.dispose();
}

/**
 * Fetch the top-level metadata (memoized; shares the chunk-prefetcher's
 * promise), pick a tier, and install the cubemap-skybox bundle as
 * `scene.background`. When a ContextManager is given (the debug tuner passes
 * none), also publishes the bundle's credit fields onto `ctx.credits.skybox`
 * for the in-map attribution popover.
 * Fire-and-forget from the renderer init path — errors (including a missing
 * skybox block) are swallowed with a console warning so the scene falls back
 * to its default black background instead of breaking.
 */
export async function loadSkybox(
	scene: Scene,
	renderer: WebGLRenderer,
	ctx?: ContextManager
): Promise<void> {
	try {
		const meta = await fetchMetadata();
		if (!meta.skybox) return;
		if (ctx)
			ctx.credits.skybox = {
				source: meta.skybox.source,
				organisation: meta.skybox.organisation,
				license: meta.skybox.license,
				attribution: meta.skybox.attribution,
				description: meta.skybox.description
			};
		await loadFromMeta(scene, renderer, meta.skybox);
	} catch (err) {
		console.warn('Failed to load skybox:', err);
	}
}
