import { MeshStandardMaterial, type Scene, type Texture, type TextureLoader } from 'three';
import { bodyMeshColor } from '$lib/utils';
import { kmToScene } from '$lib/math/units';
import { ObjectType } from '$lib/types/objects';
import { versionedUrl } from '$lib/fetch/data-base';
import { jdToDate } from '$lib/format/date';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { getSettings } from '$lib/state/settings.svelte';
import { isLowEndDevice } from '$lib/device';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { getLabelVariant, setLabelName } from '../../label/factory';
import { attachDisplacementMap, disposeDisplacementFromMaterial } from '../surface/displacement';
import { attachSelfShadowToBody, detachSelfShadow } from '../surface/self-shadow';
import { syncAtmosphereEllipsoid } from '../surface/atmosphere';
import { attachRingBundles } from '../surface/ring-attach';
import { syncSunTransmittanceUniforms } from '../surface/sun-transmittance';
import { setShapeModelMap, setSurfaceMap } from './model-texture';
import type { BodyObjects } from '../../types';
import { applyBodyOrientation } from './orientation-apply';

/** Ordered tier names: lower → higher resolution. Index = rank. */
export const TIER_NAMES = ['low', 'medium', 'high'] as const;
export type TierName = (typeof TIER_NAMES)[number];

/** Numeric rank for `tier` (0=low … 2=high), or -1 if unrecognised. */
export function tierRank(tier: string | undefined): number {
	if (tier === undefined) return -1;
	return TIER_NAMES.indexOf(tier as TierName);
}

/**
 * Highest tier in `available` whose rank is ≤ `maxRank`, or undefined if none
 * qualify. Shared by the LOD pass: surface stepping up to the screen-size
 * target, or cloud clamping down to whatever tiers its bundle ships.
 */
export function highestAvailableTier(maxRank: number, available: string[]): TierName | undefined {
	for (let r = maxRank; r >= 0; r--) {
		const name = TIER_NAMES[r];
		if (available.includes(name)) return name;
	}
	return undefined;
}

/**
 * URL for a body's texture at a given tier/frame: `{tier}.webp`, or
 * `{tier}_NN.webp` for monthly bodies (see docs/export-format/textures.md).
 */
function textureUrlFor(id: string, tier: string, frame: number | undefined): string {
	if (frame === undefined) return versionedUrl(`/v1/textures/${id}/${tier}.webp`, 'textures');
	return versionedUrl(
		`/v1/textures/${id}/${tier}_${String(frame).padStart(2, '0')}.webp`,
		'textures'
	);
}

/**
 * Which frame of a multi-frame texture to show for `jd`. Only 12 (monthly)
 * is supported today, so the answer is just the UTC month.
 */
export function textureFrameForJd(jd: number, frames: number | undefined): number | undefined {
	if (!frames || frames < 2) return undefined;
	if (frames === 12) return jdToDate(jd).getUTCMonth() + 1;
	return 1;
}

/** Load a texture tier/frame and swap it onto the body's material, disposing the prior map. */
async function swapBodyTexture(
	bo: BodyObjects,
	tier: string,
	frame: number | undefined,
	textureLoader: TextureLoader
): Promise<void> {
	if (!bo.mesh) return;
	const fileId = bo.body.data.id;
	const gen = (bo.textureLoadGen ??= 0);
	bo.textureLoading = true;
	try {
		const texture = await new Promise<Texture>((resolve, reject) => {
			textureLoader.load(textureUrlFor(fileId, tier, frame), resolve, undefined, reject);
		});
		// Unloaded (debug toggle off / refocus) while in flight — don't re-attach.
		if (!bo.mesh || bo.textureLoadGen !== gen) {
			texture.dispose();
			return;
		}
		const material = bo.mesh.material as MeshStandardMaterial;
		setSurfaceMap(material, texture, bo.body.data.color);
		// A loaded shape model samples the same map (equirect-projected).
		if (bo.model)
			setShapeModelMap(bo.model, texture, bodyMeshColor(bo.body.data), bo.body.data.color);
		bo.textureTier = tier;
		bo.textureFrame = frame;
	} catch (err) {
		console.warn(`Failed to load ${tier} texture for ${fileId}:`, err);
	} finally {
		bo.textureLoading = false;
	}
}

/**
 * Scale the mesh's uniform sphere into an ellipsoid with semi-axes (a, b, c)
 * km. The applyOrientation basis maps SPICE (X, Y, Z) to mesh local (X, Z, Y),
 * so X→a, Y→c, Z→b. `radiusScene` is bumped to the largest extent so
 * halo/label/LOD/occlusion checks match what's rendered. Marks
 * `bo.radiiApplied` so callers don't re-scale the same mesh.
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
	// Mesh-local x/y/z semi-axes (matches the scale order) for ellipsoid occlusion.
	bo.semiAxesScene = [kmToScene(a), kmToScene(c), kmToScene(b)];
	// Reshape the scattering shell to match, and re-normalise sun-transmittance —
	// their baked mean-radius heights would put the equator off the datum otherwise.
	if (bo.atmosphere) {
		const eqKm = Math.max(a, b);
		syncAtmosphereEllipsoid(bo.atmosphere, eqKm, c, kmToScene(eqKm));
		for (const u of bo.sunTint ?? []) {
			syncSunTransmittanceUniforms(u, bo.atmosphere.params, kmToScene(eqKm), eqKm);
		}
	}
	bo.radiiApplied = true;
}

/**
 * Initial low-tier texture load for standalone bodies (not part of a
 * pre-declared system — loadSystemData covers those). Also applies
 * orientation, triaxial radii, and ring bundles from the global JSON, and
 * forwards texture attribution to `ctx` so standalones (Bennu, Ceres) get
 * credited the same as system bodies.
 */
export async function loadBodyTexture(
	bo: BodyObjects,
	textureLoader: TextureLoader,
	currentJd: number,
	scene: Scene,
	maxTextureSize: number,
	ctx?: ContextManager
): Promise<void> {
	if (bo.textureTier || bo.textureLoading) return;
	// Texture/orientation/radii live in `detail.global`; the localized bundle
	// only carries the display name.
	const detail = await fetchObjectDetail(bo.body.data.id, false);
	if (!detail.global) return;

	// Runs before the map-texture early-return so bodies without a surface
	// map (most asteroids) still get their ellipsoid shape and spin axis.
	if (detail.global.orientation && !bo.body.orientation) {
		applyBodyOrientation(bo, detail.global.orientation, ctx);
	}
	// Absolute-radius DEM bodies (Vesta/Ceres) skip triaxial — the displacement
	// already carries the full shape.
	if (
		detail.global.radii &&
		bo.radiusScene > 0 &&
		!bo.radiiApplied &&
		!detail.global.displacement?.absolute_radius
	) {
		applyRadiiToMesh(bo, detail.global.radii);
	}

	// Ring annuli for the ringed small bodies — before the texture early-return,
	// since none of the four has a surface map.
	if (detail.global.rings?.length) {
		await Promise.allSettled(
			attachRingBundles(
				bo.body.data.id,
				bo.body.data.id,
				detail.global.rings,
				detail.global.radii,
				bo,
				scene,
				maxTextureSize,
				ctx
			)
		);
	}

	// Physically-derived surface colour, applied here since it rides the global
	// bundle fetched on focus. The untextured sphere adopts it; point cloud/label
	// keep their per-type tint via resolveBodyColor. Small bodies carry it under
	// `sbdb`, moons top-level.
	const surfaceColor = detail.global.sbdb?.color ?? detail.global.color;
	if (surfaceColor) {
		bo.body.data.color = surfaceColor;
		if (bo.mesh && !bo.textureTier) {
			(bo.mesh.material as MeshStandardMaterial).color.set(surfaceColor);
		}
	}

	if (!detail.global.map_texture_available) return;
	if (ctx && detail.global.texture) {
		// Standalones aren't tied to a system barycenter; key the credit on the
		// body itself so it matches the focused body id.
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
	// DEM sibling — standalones load it here since they skip the per-system
	// path (same shape as system.ts's branch). Low-end clients keep the flat
	// textured sphere: the DEM relief is the heaviest per-body asset.
	if (detail.global.displacement && !bo.displacementMap && bo.mesh && isLowEndDevice()) {
		console.info(`Low-end device: skipping DEM relief for ${bo.body.data.id}`);
	} else if (
		detail.global.displacement &&
		!bo.displacementMap &&
		bo.mesh &&
		getSettings().showDisplacement
	) {
		const dispMeta = detail.global.displacement;
		if (ctx) {
			ctx.credits.registerDisplacement({
				bodyId: bo.body.data.id,
				systemId: bo.body.data.id,
				source: dispMeta.source,
				organisation: dispMeta.organisation,
				attribution: dispMeta.attribution,
				description: dispMeta.description
			});
		}
		const material = bo.mesh.material as MeshStandardMaterial;
		const tex = await attachDisplacementMap(
			material,
			dispMeta,
			'low',
			textureLoader,
			bo.radiusScene
		);
		if (tex) {
			bo.displacementMap = tex;
			bo.displacementMeta = dispMeta;
			bo.displacementTier = 'low';
			// Debug: self-shadow off → relief without in-shader cast shadows.
			bo.selfShadow = getSettings().showSelfShadow
				? attachSelfShadowToBody(material, tex, kmToScene(dispMeta.scale_km))
				: null;
		}
	}

	if (bo.textureTier || bo.textureLoading) return;
	// Debug: surface texture off → the sphere shows its flat base tint only.
	if (!getSettings().showSurfaceTexture) return;
	bo.availableTiers ??= [...TIER_NAMES];
	bo.availableFrames = detail.global.texture?.frames;
	await swapBodyTexture(bo, 'low', textureFrameForJd(currentJd, bo.availableFrames), textureLoader);
}

/**
 * Fill in a click-promoted body's label name by lazily fetching its detail
 * bundle — e.g. a random asteroid swaps blank → Wikidata name a bit later.
 * No-op if already named, or labeled with `variant: 'none'` (debris, etc.).
 */
export async function loadBodyLabel(bo: BodyObjects): Promise<void> {
	if (!bo.label) return;
	const data = bo.body.data;
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

/** Drop a body's loaded texture, reverting its material to base tint. No-op if nothing is loaded. */
export function unloadBodyTexture(bo: BodyObjects): void {
	if (!bo.mesh) return;
	// Invalidate any in-flight swap so it won't re-attach after we tear down.
	bo.textureLoadGen = (bo.textureLoadGen ?? 0) + 1;
	const material = bo.mesh.material as MeshStandardMaterial;
	if (bo.displacementMap) {
		disposeDisplacementFromMaterial(material);
		bo.displacementMap = null;
		bo.displacementTier = undefined;
		detachSelfShadow(bo.selfShadow);
		bo.selfShadow = null;
	}
	if (!material.map) return;
	material.map.dispose();
	material.map = null;
	material.color.set(bodyMeshColor(bo.body.data));
	material.needsUpdate = true;
	// Don't leave the model sampling the disposed texture.
	if (bo.model) setShapeModelMap(bo.model, null, bodyMeshColor(bo.body.data));
	bo.textureTier = undefined;
}

/** Load a specific texture tier/frame onto a body's material. No-op if already
 *  loaded, the tier is unavailable, or another load is in flight. */
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
