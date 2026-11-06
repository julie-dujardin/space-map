import { type Scene, SphereGeometry, type TextureLoader } from 'three';
import { kmToScene } from '$lib/math/units';
import { effectiveRadiusKm, ObjectType, type PositionedBody } from '$lib/types/objects';
import { applyOrientation, type NutPrecSums } from '$lib/math/orientation';
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
import {
	loadSiblingLayers,
	type SiblingBundles,
	type SiblingLoadEnv,
	unloadSiblingLayers
} from './sibling-layers';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import {
	applyRadiiToMesh,
	applySurfaceColour,
	loadBodyTextureTier,
	textureFrameForJd,
	unloadBodyTexture
} from './textures';

/** The maps of a body as a system file gives them. A planet of another star
 *  carries the same keys in its record. */
export interface SurfaceMaps extends SiblingBundles {
	tiers?: string[];
	/** Maps ranked below `texture`, best first. A viewer that may not serve
	 *  the best map falls back to them. Each names its own bundle and tiers. */
	alternates?: (NonNullable<SurfaceMaps['texture']> & { id: string; tiers: string[] })[];
	/** The credit block, as `export/systems.py::texture_attribution` writes it. */
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
		/** An artist's picture of a body no camera has resolved. */
		artist_impression?: boolean;
	};
}

interface SystemBodyMeta extends SurfaceMaps {
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
	nut_prec?: NutPrecSums;
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
		applyBodyOrientation(body, record.orientation, record.nut_prec, ctx, barycenterId!);
	} else if (detail?.global?.orientation) {
		applyBodyOrientation(body, detail.global.orientation, detail.global.nut_prec, ctx);
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

/** A body's map as {@link loadSystemData} draws it. */
type PickedSurface = NonNullable<SurfaceMaps['texture']> & { id: string; tiers?: string[] };

/**
 * The best map of `maps` this embed may serve, which is not always the best
 * one there is. The body's own bundle is named by the body; a fallback names
 * itself. Undefined where none is reachable: the body keeps its fallback colour.
 */
export function surfaceOf(bodyId: string, maps: SurfaceMaps): PickedSurface | undefined {
	const best = maps.texture && { ...maps.texture, id: bodyId, tiers: maps.tiers };
	return pickTexture<PickedSurface>([best, ...(maps.alternates ?? [])]);
}

/** Whether a body draws a surface map: one is servable and it has tiers to
 *  load. The debug setting for surface maps only hides the map. */
export function drawsSurfaceMap(bodyId: string, maps: SurfaceMaps): boolean {
	return !!surfaceOf(bodyId, maps)?.tiers?.length;
}

/**
 * Start the loads of a body's surface map at its base tier and of its sibling
 * bundles. Per-frame LOD upgrades the map from there. A body that has a map
 * already keeps it, so a repeat visit does not drop high to low.
 */
function loadSurfaceMaps(
	bodyId: string,
	systemId: string,
	maps: SurfaceMaps,
	surface: PickedSurface | undefined,
	bo: BodyObjects,
	env: SiblingLoadEnv
): Promise<void>[] {
	const started: Promise<void>[] = [];
	if (surface?.tiers?.length) {
		bo.availableTiers = surface.tiers;
		bo.availableFrames = surface.frames;
		bo.textureBundleId = surface.id === bodyId ? undefined : surface.id;
		bo.surfaceTiles = surface.tiles;
		bo.artistImpression = surface.artist_impression;
		if (!bo.textureTier) {
			const frame = textureFrameForJd(env.currentJd, bo.availableFrames);
			started.push(loadBodyTextureTier(bo, 'low', frame, env.textureLoader));
		}
	}
	// Specular, night lights, glow, DEM relief and the cloud overlay.
	started.push(...loadSiblingLayers(bodyId, systemId, maps, bo, env));
	return started;
}

/** The planet bodies whose maps were asked for. A body is built again when its
 *  planet comes back, so each build asks once. */
const planetMapsAsked = new WeakSet<BodyObjects>();

/**
 * Credit and load the maps of each planet of another star in `bodies` that
 * has a sphere, from its record in the system file. Credits are scoped to the
 * system's key star. A planet whose maps were asked for already is skipped.
 * Returns the loads it started, or null for none.
 */
export function loadPlanetMaps(
	bodies: readonly PositionedBody[],
	env: SiblingLoadEnv & { bodyObjects: Map<string, BodyObjects> }
): Promise<unknown> | null {
	const started: Promise<void>[] = [];
	for (const body of bodies) {
		const anchor = body.exoplanet;
		const bo = env.bodyObjects.get(body.data.id);
		if (!anchor || !bo?.mesh || planetMapsAsked.has(bo)) continue;
		planetMapsAsked.add(bo);
		const systemId = extrasolarObjectId(anchor.system);
		const surface = surfaceOf(body.data.id, anchor.planet);
		if (surface) env.ctx?.credits.registerImagery('surface', body.data.id, systemId, surface);
		started.push(...loadSurfaceMaps(body.data.id, systemId, anchor.planet, surface, bo, env));
	}
	return started.length ? Promise.allSettled(started) : null;
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
		const surface = surfaceOf(bodyId, bodyMeta);
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
			applyBodyOrientation(bo.body, bodyMeta.orientation, bodyMeta.nut_prec, ctx, barycenterId);
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

		promises.push(
			...loadSurfaceMaps(bodyId, barycenterId, bodyMeta, surface, bo, {
				textureLoader,
				currentJd,
				ctx
			})
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
