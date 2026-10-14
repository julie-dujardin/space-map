import { type Scene, SphereGeometry, type TextureLoader } from 'three';
import { kmToScene } from '$lib/math/units';
import { effectiveRadiusKm, ObjectType, type PositionedBody } from '$lib/types/objects';
import { applyOrientation } from '$lib/math/orientation';
import { getNutPrecPhases, ownerIdFor } from '$lib/fetch/systems-global';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { dataBase } from '$lib/fetch/data-base';
import { fetchWithTimeout } from '$lib/fetch/fetch-timeout';
import { pickTexture, type TextureDistribution } from '$lib/host';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { disposeRingNode, type RingMeta } from '../surface/rings';
import { attachRingBundles } from '../surface/ring-attach';
import { disposeNomenclatureLabels } from '../surface/nomenclature';
import type { BodyObjects, TilesBlock } from '../../types';
import { applyBodyOrientation } from './orientation-apply';
import { loadSiblingLayers, type SiblingBundles, unloadSiblingLayers } from './sibling-layers';
import {
	applyRadiiToMesh,
	applySurfaceColour,
	loadBodyTextureTier,
	textureFrameForJd,
	unloadBodyTexture
} from './textures';

interface SystemBodyMeta extends SiblingBundles {
	tiers?: string[];
	/** Attribution block — matches `export/systems.py::texture_attribution`. */
	/** Maps ranked below `texture`, best first — the fallbacks for a viewer
	 *  that may not serve the best one. Each names its own bundle and tiers. */
	alternates?: (NonNullable<SystemBodyMeta['texture']> & { id: string; tiers: string[] })[];
	texture?: {
		source: string;
		organisation: string;
		license?: string;
		/** Who may serve it; absent where anyone may. */
		distribution?: TextureDistribution;
		type: string;
		attribution?: string;
		description?: string;
		/** Only on `cylindrical_monthly`: number of monthly frames (always 12 today). */
		frames?: number;
		tiles?: TilesBlock;
	};
	orientation?: {
		pole_ra_0: number;
		pole_ra_1: number;
		pole_dec_0: number;
		pole_dec_1: number;
		w0: number;
		w1: number;
		w2: number;
	};
	/** Per-body IAU nutation/precession coefficients (paired with global angles). */
	nut_prec?: { ra: number[]; dec: number[]; pm: number[] };
	/** SPICE PCK triaxial radii (km) along body-fixed X, Y, Z (Z = spin axis). */
	radii?: { a: number; b: number; c: number };
	/** Ring bundles, inner → outer. Split per opacity range (Saturn has
	 *  three) since one 8-bit strip can't span six orders of magnitude. */
	rings?: RingMeta[];
	/** As on the object: the measured colour, its albedo and the law of the
	 *  ground, so that a body out of focus has them too. */
	color?: string;
	geometric_albedo?: number;
	lunar_weight_scale?: number;
}

type SystemMeta = Record<string, SystemBodyMeta>;

/** System files on their way: the spin of a landing body and the system in
 *  focus can ask for the same one at the same time. */
const systemMetaLoads = new Map<string, Promise<SystemMeta | null>>();

/** The file of the system of `barycenterId`: a record per body. Null when the
 *  export has none. Rejects when it did not load. */
function fetchSystemMeta(barycenterId: string): Promise<SystemMeta | null> {
	let load = systemMetaLoads.get(barycenterId);
	if (!load) {
		load = downloadSystemMeta(barycenterId).finally(() => systemMetaLoads.delete(barycenterId));
		systemMetaLoads.set(barycenterId, load);
	}
	return load;
}

async function downloadSystemMeta(barycenterId: string): Promise<SystemMeta | null> {
	const resp = await fetchWithTimeout(`${dataBase()}/v1/systems/${barycenterId}.json`);
	if (resp.status === 404) return null;
	if (!resp.ok) throw new Error(`systems/${barycenterId}.json: ${resp.status}`);
	return resp.json();
}

/** Give `body` the spin of its system record: the pole and the rate, and the
 *  nutation terms joined with the angles its system shares. */
function adoptSystemSpin(
	body: PositionedBody,
	orientation: NonNullable<SystemBodyMeta['orientation']>,
	nutPrec: SystemBodyMeta['nut_prec'],
	ctx: ContextManager | undefined,
	barycenterId: string
): void {
	applyBodyOrientation(body, orientation, ctx, barycenterId);
	if (!nutPrec) return;
	const naifMatch = body.data.id.match(/^naif-(-?\d+)$/);
	const naifId = naifMatch ? parseInt(naifMatch[1], 10) : null;
	const phases = naifId !== null ? getNutPrecPhases(ownerIdFor(naifId)) : undefined;
	if (phases) body.nutPrec = { ...nutPrec, ...phases };
}

/**
 * Read how `body` spins, with no mesh to turn. The scene reads a spin with the
 * system or the texture of the body in focus, and a lander is placed from the
 * spin of the body it stands on before it has the focus.
 *
 * Rejects when a file did not load.
 */
export async function readSpin(body: PositionedBody, ctx: ContextManager): Promise<void> {
	const id = body.data.id;
	const known = (): boolean => !!body.orientation || ctx.bodies.orientationRead.has(id);
	if (known()) return;
	const systemId = ctx.visibility.resolveSystemId(body);
	const system = systemId ? ctx.getBody(systemId) : undefined;
	// A small body is its own system, and has no system file.
	const barycenterId = system?.data.objectType === ObjectType.BARYCENTER ? system.data.id : null;
	const record = barycenterId ? (await fetchSystemMeta(barycenterId))?.[id] : undefined;
	const detail = record?.orientation ? null : await fetchObjectDetail(id, false);
	// The system in focus, or another read, can give the spin in the meantime.
	if (known()) return;
	if (record?.orientation) {
		adoptSystemSpin(body, record.orientation, record.nut_prec, ctx, barycenterId!);
	} else if (detail?.global?.orientation) {
		applyBodyOrientation(body, detail.global.orientation, ctx);
	}
	ctx.bodies.orientationRead.add(id);
	if (body.orientation) ctx.bodies.orientationVersion++;
}

/** {@link readSpin} for the body the probe `probeId` stands on at `jd`. */
export async function readLandingBodySpin(
	probeId: string,
	jd: number,
	ctx: ContextManager
): Promise<void> {
	const landingBodyId = ctx.probeStore?.landingBodyAt(probeId, jd);
	const landingBody = landingBodyId ? ctx.getBody(landingBodyId) : undefined;
	if (landingBody) await readSpin(landingBody, ctx);
}

/**
 * Fetch and apply system metadata (textures, orientation, rings) to every
 * body in the system, keyed by barycenter ID (naif-3, naif-5, …).
 */
export async function loadSystemData(
	barycenterId: string,
	bodyObjects: Map<string, BodyObjects>,
	scene: Scene,
	textureLoader: TextureLoader,
	currentJd: number,
	maxTextureSize: number,
	ctx?: ContextManager
): Promise<void> {
	const meta = await fetchSystemMeta(barycenterId).catch(() => null);
	if (!meta) return;

	const promises: Promise<void>[] = [];
	for (const [bodyId, bodyMeta] of Object.entries(meta)) {
		// The best map this embed may serve, which is not always the best one
		// there is. Credit follows the picture actually drawn; where none is
		// reachable the body keeps its fallback colour, as an untextured one does.
		// The body's own bundle is named by the body; a fallback names itself.
		// Normalised to one shape so the pick doesn't care which it got.
		const best = bodyMeta.texture && { ...bodyMeta.texture, id: bodyId, tiers: bodyMeta.tiers };
		const surface = pickTexture([best, ...(bodyMeta.alternates ?? [])]);
		if (surface) ctx?.credits.registerImagery('surface', bodyId, barycenterId, surface);
		const bo = bodyObjects.get(bodyId);
		if (!bo?.mesh) continue;
		ctx?.bodies.orientationRead.add(bodyId);

		// So that a body out of focus has them too. The object bundle of the
		// body in focus can have given them first.
		const data = bo.body.data;
		data.color ??= bodyMeta.color;
		data.geometricAlbedo ??= bodyMeta.geometric_albedo;
		data.lunarWeightScale ??= bodyMeta.lunar_weight_scale;
		if (bo.photometry) bo.photometry.uLunarWeightScale.value = data.lunarWeightScale ?? 1;
		applySurfaceColour(bo);

		// Apply orientation (axial tilt + spin) and cache for per-frame re-application.
		if (bodyMeta.orientation) {
			adoptSystemSpin(bo.body, bodyMeta.orientation, bodyMeta.nut_prec, ctx, barycenterId);
			applyOrientation(bo.mesh, bodyMeta.orientation, currentJd, bo.body.nutPrec);
		}

		// Triaxial flattening: SPICE (X, Y, Z) maps to mesh local (X, Z, Y) per
		// applyOrientation's basis. Skipped when a DEM already carries the full
		// shape (Vesta, Ceres) to avoid double-counting it.
		if (
			bodyMeta.radii &&
			bo.radiusScene > 0 &&
			!bo.radiiApplied &&
			!bodyMeta.displacement?.absolute_radius
		) {
			applyRadiiToMesh(bo, bodyMeta.radii);
		}

		// Load the base tier once; per-frame LOD upgrades from there. Skip if
		// already loaded so repeat visits don't downgrade high → low. A fallback
		// map is its own bundle, so the id the tiers hang off is its, not the
		// body's.
		if (surface?.tiers?.length) {
			bo.availableTiers = surface.tiers;
			bo.availableFrames = surface.frames;
			bo.textureBundleId = surface.id === bodyId ? undefined : surface.id;
			bo.surfaceTiles = surface.tiles;
			if (!bo.textureTier) {
				const frame = textureFrameForJd(currentJd, bo.availableFrames);
				promises.push(loadBodyTextureTier(bo, 'low', frame, textureLoader));
			}
		}

		// Specular, night lights, DEM relief and the cloud overlay.
		promises.push(
			...loadSiblingLayers(bodyId, barycenterId, bodyMeta, bo, { textureLoader, currentJd, ctx })
		);

		// Ring annuli, one node per bundle (Saturn has three).
		if (bodyMeta.rings?.length) {
			promises.push(
				...attachRingBundles(
					bodyId,
					barycenterId,
					bodyMeta.rings,
					bodyMeta.radii,
					bo,
					scene,
					maxTextureSize,
					ctx
				)
			);
		}
	}
	await Promise.allSettled(promises);
}

/**
 * Release GPU textures (and rings) for every body in `barycenterId`, keeping
 * geometry/mesh intact. Counterpart to {@link loadSystemData}, called on
 * leaving a system so it stops pinning high-tier textures on the GPU.
 */
export function unloadSystemTextures(
	barycenterId: string,
	bodyObjects: Map<string, BodyObjects>,
	scene: Scene,
	ctx: ContextManager
): void {
	for (const bo of bodyObjects.values()) {
		if (!ctx.visibility.isBodyInSystem(bo.body, barycenterId)) continue;
		unloadBodyTexture(bo);
		unloadSiblingLayers(bo);
		// A terrain window is ~100k vertices; drop back to the plain sphere on unload.
		if (bo.terrainWindow && bo.mesh) {
			bo.terrainWindow = null;
			const radius = kmToScene(effectiveRadiusKm(bo.body.data));
			const old = bo.mesh.geometry;
			bo.mesh.geometry = new SphereGeometry(radius, 24, 24);
			old.dispose();
			bo.currentSegments = 24;
		}
		for (const ring of bo.rings) {
			ring.planetShadow?.disable();
			ring.ringshine?.disable();
			ring.mesh.removeFromParent();
			disposeRingNode(ring);
		}
		bo.rings = [];
		disposeNomenclatureLabels(bo);
	}
}
