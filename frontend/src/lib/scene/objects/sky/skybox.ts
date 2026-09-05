/**
 * Celestial-sphere skybox (`scene.background`). Cube faces from the NASA SVS
 * Deep Star Maps 2020 EXR (equatorial equirectangular, via py360convert),
 * tier auto-selected from `renderer.capabilities.maxTextureSize`.
 *
 * The SVS map is J2000 equatorial; the scene is J2000 ecliptic. The
 * analytical equinox/NCP rotation lands 180° off what the EXR delivers —
 * root cause unresolved. Corrected empirically with a 180° post-rotation
 * about scene-frame RA=18h, verified against Polaris, Sirius, and the
 * Magellanic Clouds.
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
import { currentRenderTier } from '$lib/scene/render-tier';

const DEG2RAD = Math.PI / 180;
const OBLIQUITY_RAD = EARTH_OBLIQUITY_DEG * DEG2RAD;

/** Composed analytical + empirical rotation: `Rₓ(−π/2) · Rᵧ(π/2 − ε) · R_z(−π/2)`. */
export const SKYBOX_BASE_ROTATION = new Quaternion()
	.setFromAxisAngle(new Vector3(0, 0, 1), -Math.PI / 2)
	.premultiply(new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), Math.PI / 2 - OBLIQUITY_RAD))
	.premultiply(new Quaternion().setFromAxisAngle(new Vector3(1, 0, 0), -Math.PI / 2));

/** Face order Three.js' `CubeTextureLoader` expects: +X −X +Y −Y +Z −Z.
 *  Matches the exporter's `{tier}_{face}.webp` naming. */
const FACE_ORDER = ['px', 'nx', 'py', 'ny', 'pz', 'nz'] as const;

/**
 * Largest tier whose per-face edge is ≤ `maxTextureSize`, falling back to the
 * smallest tier rather than going blank on very constrained devices.
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
 * Fetch + decode one tier's six faces as ImageBitmaps, off-thread via
 * `createImageBitmap` — avoids the ~1s main-thread stall `texSubImage2D`
 * pays converting the 4k tier. `imageOrientation: 'none'` matches the
 * `<img>` path's flipY=false upload, keeping SKYBOX_BASE_ROTATION valid.
 */
async function loadTierBitmaps(
	id: string,
	tier: string,
	priority?: RequestPriority
): Promise<ImageBitmap[]> {
	return Promise.all(
		FACE_ORDER.map(async (face) => {
			const res = await fetch(faceUrl(id, tier, face), { priority });
			if (!res.ok) throw new Error(`Skybox face fetch failed (${res.status}): ${tier}_${face}`);
			const blob = await res.blob();
			return createImageBitmap(blob, { imageOrientation: 'none', premultiplyAlpha: 'none' });
		})
	);
}

/** Fetch+decode promises, shared so the early prefetch and the install reuse
 *  one fetch per tier. Entries are dropped (and bitmaps closed) once the tier
 *  is on the GPU — the decoded faces are ~480MB across tiers, far too much to
 *  keep as a CPU-side copy for the whole session. */
const tierPrefetch = new Map<string, Promise<ImageBitmap[]>>();

function tierKey(id: string, tier: string): string {
	return `${id}:${tier}`;
}

function tierBitmaps(id: string, tier: string, priority?: RequestPriority): Promise<ImageBitmap[]> {
	const key = tierKey(id, tier);
	let p = tierPrefetch.get(key);
	if (!p) {
		p = loadTierBitmaps(id, tier, priority);
		tierPrefetch.set(key, p);
	}
	return p;
}

/** Drop the cache entry and free the decoded faces. The CubeTexture keeps
 *  referencing the closed bitmaps, so it can never re-upload — context
 *  restore must go through a full skybox reload instead. */
function releaseTierBitmaps(id: string, tier: string, bitmaps: ImageBitmap[]): void {
	tierPrefetch.delete(tierKey(id, tier));
	for (const b of bitmaps) b.close();
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
 * Start fetching the low skybox tier as soon as metadata is known, without
 * waiting for the renderer. Low only: the full tier is an order of magnitude
 * larger and waits behind the eager-minors gate (see {@link loadFromMeta}).
 */
export function prefetchSkyboxTiers(meta: SkyboxMetadata): void {
	const low = pickLowTier(meta);
	if (low) void tierBitmaps(meta.id, low).catch(() => tierPrefetch.delete(tierKey(meta.id, low)));
}

/** Full-res tier load waits on the eager point cloud, but never longer than this. */
const FULL_TIER_GATE_TIMEOUT_MS = 12_000;

async function loadFromMeta(
	scene: Scene,
	renderer: WebGLRenderer,
	meta: SkyboxMetadata
): Promise<void> {
	const tier = pickTier(
		meta,
		Math.min(renderer.capabilities.maxTextureSize, currentRenderTier().maxSkyboxFace)
	);
	if (!tier) {
		console.warn(`Skybox ${meta.id}: no tiers declared`);
		return;
	}
	// `scene.backgroundRotation` is owned by the renderer (SceneRenderer.
	// setSkyboxAdjust), which seeds it synchronously at init — writing it here
	// would risk clobbering a user adjustment that raced ahead of this load.
	const lowTier = pickLowTier(meta);
	// Holder: TS can't narrow an async-race assignment through a plain `let`.
	const lowRef: { cube: CubeTexture | null; bitmaps: ImageBitmap[] | null } = {
		cube: null,
		bitmaps: null
	};
	let fullInstalled = false;
	if (lowTier && lowTier !== tier) {
		// Install low only if it wins the race, so a cached full tier goes straight up.
		void tierBitmaps(meta.id, lowTier)
			.then((bitmaps) => {
				// Full already up: the low faces were fetched for nothing — free them.
				if (fullInstalled) {
					releaseTierBitmaps(meta.id, lowTier, bitmaps);
					return;
				}
				lowRef.cube = makeCube(bitmaps);
				lowRef.bitmaps = bitmaps;
				scene.background = lowRef.cube;
				performance.mark('sm-skybox-low');
			})
			.catch(() => {});
	}
	// Full tier is large (≈11MB) — hold it until the eager minor wave has its
	// bandwidth, bounded by a timeout so a stalled load doesn't strand us on low.
	// A tier capped to low is small and goes up at once.
	if (tier !== lowTier) {
		await Promise.race([
			eagerMinorsDone,
			new Promise<void>((resolve) => setTimeout(resolve, FULL_TIER_GATE_TIMEOUT_MS))
		]);
	}
	// Low priority: the minor-body long tail is still streaming and matters more.
	const fullBitmaps = await tierBitmaps(meta.id, tier, tier === lowTier ? undefined : 'low');
	const full = makeCube(fullBitmaps);
	// Upload during idle time so the first sampling render doesn't absorb the cost.
	await new Promise<void>((resolve) =>
		'requestIdleCallback' in window
			? requestIdleCallback(() => resolve(), { timeout: 2000 })
			: setTimeout(resolve, 500)
	);
	renderer.initTexture(full);
	fullInstalled = true;
	const prevBackground = scene.background;
	scene.background = full;
	performance.mark('sm-skybox-high');
	lowRef.cube?.dispose();
	// A context-restore reload replaces an earlier full cube; free its GL slot.
	if (prevBackground && prevBackground !== lowRef.cube && prevBackground instanceof CubeTexture)
		prevBackground.dispose();
	// The GPU now holds the only copy that matters; the decoded faces would
	// otherwise pin ~480MB of CPU RAM for the session.
	releaseTierBitmaps(meta.id, tier, fullBitmaps);
	if (lowTier && lowTier !== tier && lowRef.bitmaps)
		releaseTierBitmaps(meta.id, lowTier, lowRef.bitmaps);
}

/**
 * Fetch metadata, pick a tier, and install the cubemap skybox as
 * `scene.background`. Publishes credit fields onto `ctx.credits.skybox` when
 * given. Fire-and-forget from renderer init — errors are swallowed with a
 * warning so the scene falls back to black instead of breaking.
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
