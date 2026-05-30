import { MeshStandardMaterial, SRGBColorSpace, type Texture, type TextureLoader } from 'three';
import { resolveBodyColor } from '$lib/utils';
import { kmToScene } from '$lib/math/units';
import { ObjectType } from '$lib/types/objects';
import { DATA_BASE } from '$lib/fetch/data-base';
import { jdToDate } from '$lib/format/date';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { getLabelVariant, setLabelName } from '../../label/factory';
import type { BodyObjects } from '../../types';

/** Ordered tier names: lower → higher resolution. Index = rank. */
export const TIER_NAMES = ['low', 'medium', 'high'] as const;
export type TierName = (typeof TIER_NAMES)[number];

/** Numeric rank for `tier` (0=low … 2=high), or -1 if unrecognised. */
export function tierRank(tier: string | undefined): number {
	if (tier === undefined) return -1;
	return TIER_NAMES.indexOf(tier as TierName);
}

/**
 * Highest tier in `available` whose rank is ≤ `maxRank`. Returns undefined
 * when no tier ≤ `maxRank` is exported. Shared by the per-frame texture LOD
 * pass for both surface and cloud bundles: the surface caller uses it to
 * step from the current tier up to the screen-size target; the cloud caller
 * uses it to clamp the surface's current tier down to whatever the cloud
 * bundle actually ships (which may stop short of `high`).
 */
export function highestAvailableTier(maxRank: number, available: string[]): TierName | undefined {
	for (let r = maxRank; r >= 0; r--) {
		const name = TIER_NAMES[r];
		if (available.includes(name)) return name;
	}
	return undefined;
}

/**
 * URL for a body's texture at a given tier/frame. Single-frame bodies use
 * `{tier}.webp`; monthly bodies append a 1-based zero-padded frame suffix
 * (`{tier}_NN.webp`, `NN` = 01..frames). Mirrors the export-tree convention
 * documented in docs/export-format.md.
 */
function textureUrlFor(id: string, tier: string, frame: number | undefined): string {
	if (frame === undefined) return `${DATA_BASE}/v1/textures/${id}/${tier}.webp`;
	return `${DATA_BASE}/v1/textures/${id}/${tier}_${String(frame).padStart(2, '0')}.webp`;
}

/**
 * Resolve which frame of a multi-frame texture should be shown for `jd`. The
 * only case we support today is 12 — one tile per calendar month — so the
 * answer is just the UTC month. Returns undefined when the body has no frame
 * dimension (single-frame texture).
 */
export function textureFrameForJd(jd: number, frames: number | undefined): number | undefined {
	if (!frames || frames < 2) return undefined;
	if (frames === 12) return jdToDate(jd).getUTCMonth() + 1;
	return 1;
}

/**
 * Load a texture tier/frame and swap it onto the body's material, disposing
 * the prior map. Sets `textureLoading` while in flight and `textureTier` /
 * `textureFrame` on success.
 */
async function swapBodyTexture(
	bo: BodyObjects,
	tier: string,
	frame: number | undefined,
	textureLoader: TextureLoader
): Promise<void> {
	if (!bo.mesh) return;
	const fileId = bo.body.data.id;
	bo.textureLoading = true;
	try {
		const texture = await new Promise<Texture>((resolve, reject) => {
			textureLoader.load(textureUrlFor(fileId, tier, frame), resolve, undefined, reject);
		});
		texture.colorSpace = SRGBColorSpace;
		const material = bo.mesh.material as MeshStandardMaterial;
		material.map?.dispose();
		material.map = texture;
		material.color.set(0xffffff);
		material.needsUpdate = true;
		bo.textureTier = tier;
		bo.textureFrame = frame;
	} catch (err) {
		console.warn(`Failed to load ${tier} texture for ${fileId}:`, err);
	} finally {
		bo.textureLoading = false;
	}
}

/**
 * Apply SPICE PCK triaxial radii to a body's mesh as a non-uniform scale.
 *
 * The mesh starts as a uniform `SphereGeometry(radiusScene)`; this scales
 * it into an ellipsoid with semi-axes (a, b, c) km. The applyOrientation
 * basis (pole on local +Y, ascending node on local +X) means SPICE (X, Y, Z)
 * maps to mesh local (X, Z, Y), so X→a, Y→c, Z→b. After scaling, the scalar
 * `radiusScene` is bumped to the rendered ellipsoid's largest extent so
 * halo / label / LOD / occlusion screen-size checks match what the user sees.
 *
 * Marks `bo.radiiApplied` so callers don't re-scale the same mesh.
 */
export function applyRadiiToMesh(
	bo: BodyObjects,
	radii: { a: number; b: number; c: number }
): void {
	if (!bo.mesh) return;
	const { a, b, c } = radii;
	const s = kmToScene(1) / bo.radiusScene;
	bo.mesh.scale.set(a * s, c * s, b * s);
	bo.radiusScene = kmToScene(Math.max(a, b, c));
	bo.radiiApplied = true;
}

/**
 * Initial low-tier texture load, used when focusing a body that may not be
 * part of a pre-declared system (the system-metadata path handles the rest).
 * Also forwards the texture attribution to `ctx` so the bar/popover can
 * credit standalone bodies (e.g. Bennu, Ceres) the same way it credits bodies
 * registered via loadSystemData.
 *
 * For non-system bodies this is also where SPICE orientation + triaxial radii
 * from the global JSON get applied (loadSystemData handles system bodies via
 * the per-system metadata file). Per-frame orientation re-application happens
 * in the renderer's main loop based on `bo.body.orientation`.
 */
export async function loadBodyTexture(
	bo: BodyObjects,
	textureLoader: TextureLoader,
	currentJd: number,
	ctx?: ContextManager
): Promise<void> {
	if (bo.textureTier || bo.textureLoading) return;
	// Texture/orientation/radii live in `detail.global`; the localized bundle
	// would only carry the display name, which this path doesn't read.
	const detail = await fetchObjectDetail(bo.body.data.id, false);
	if (!detail.global) return;

	// Apply orientation and triaxial radii from the global JSON. These run
	// before the map-texture early-return below so bodies without a surface
	// map (most asteroids) still get their ellipsoid shape and spin axis.
	if (detail.global.orientation && !bo.body.orientation) {
		bo.body.orientation = detail.global.orientation;
	}
	if (detail.global.radii && bo.radiusScene > 0 && !bo.radiiApplied) {
		applyRadiiToMesh(bo, detail.global.radii);
	}

	if (!detail.global.map_texture_available) return;
	if (ctx && detail.global.texture) {
		// Standalones aren't tied to a planetary system barycenter; key the
		// credit on the body itself so the bar/popover can match it against
		// the focused body id.
		const bodyId = bo.body.data.id;
		ctx.credits.registerTexture({
			bodyId,
			systemId: bodyId,
			source: detail.global.texture.source,
			organisation: detail.global.texture.organisation,
			type: detail.global.texture.type,
			attribution: detail.global.texture.attribution,
			description: detail.global.texture.description
		});
	}
	if (bo.textureTier || bo.textureLoading) return;
	bo.availableTiers ??= [...TIER_NAMES];
	bo.availableFrames = detail.global.texture?.frames;
	await swapBodyTexture(bo, 'low', textureFrameForJd(currentJd, bo.availableFrames), textureLoader);
}

/**
 * Resolve and apply the localized display name on a click-promoted body's
 * label. Bodies that show up in the global labels file (planets, moons, the
 * curated extras) already carry their name through `body.data.name` from
 * chunk parse time; this fills in the rest by lazily fetching the same
 * detail bundle the drawer uses, so e.g. clicking a random asteroid swaps
 * its label from blank → Wikidata name a few hundred ms later.
 *
 * No-op when the body already has a name, or when the label was created
 * with `variant: 'none'` (debris, etc.).
 */
export async function loadBodyLabel(bo: BodyObjects): Promise<void> {
	if (!bo.label) return;
	const data = bo.body.data;
	// Already named at chunk parse time (in the global labels file) — nothing to resolve.
	if (data.name) return;
	const detail = await fetchObjectDetail(data.id, data.hasLocalized);
	const resolved = detail.localized?.name ?? detail.global?.name;
	if (!resolved) return;
	// Don't clobber a name that arrived via another path (e.g. focus drawer
	// already wrote it onto data.name) while the bundle was in flight.
	data.name ??= resolved;
	const variant = getLabelVariant(bo.body);
	const isLarge = data.objectType === ObjectType.STAR || data.objectType === ObjectType.PLANET;
	setLabelName(bo.label, resolved, variant, isLarge);
}

/**
 * Drop a body's loaded texture and revert its material to its base tint. The
 * material/geometry/mesh stay so the body keeps rendering as a flat-shaded
 * sphere; only the GPU texture is released. No-op if nothing is loaded.
 */
export function unloadBodyTexture(bo: BodyObjects): void {
	if (!bo.mesh) return;
	const material = bo.mesh.material as MeshStandardMaterial;
	if (!material.map) return;
	material.map.dispose();
	material.map = null;
	material.color.set(resolveBodyColor(bo.body.data));
	material.needsUpdate = true;
	bo.textureTier = undefined;
}

/**
 * Load a specific texture tier (and monthly frame, if applicable) for a body
 * and swap it onto its material. No-op if the exact (tier, frame) pair is
 * already loaded, the tier is unavailable, or another load is in flight.
 */
export async function loadBodyTextureTier(
	bo: BodyObjects,
	tier: string,
	frame: number | undefined,
	textureLoader: TextureLoader
): Promise<void> {
	if (bo.textureLoading) return;
	if (!bo.availableTiers?.includes(tier)) return;
	if (bo.textureTier === tier && bo.textureFrame === frame) return;
	await swapBodyTexture(bo, tier, frame, textureLoader);
}
