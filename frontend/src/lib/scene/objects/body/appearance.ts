/**
 * The host's own imagery on a body the map already knows. A picture given here
 * replaces the one the export publishes, at every distance: the altitude-driven
 * tier swap is the map choosing between its own pictures, and there is no
 * choosing to do once a host has said what the body looks like.
 *
 * Two things hold that. The tier loader will not fetch a body's own surface
 * texture while a host picture stands, so nothing is downloaded to overwrite
 * it; and the same pass that swaps tiers checks each frame that the picture on
 * the material is still the host's, and puts it back if anything else has
 * taken it off — a system reload, a defocus, a context restore.
 */

import { SRGBColorSpace, type MeshStandardMaterial, type Texture, type TextureLoader } from 'three';
import { bodyMeshColor } from '$lib/body-color';
import type { BodyObjects } from '$lib/scene/types';
import { attachNightTexture, disposeNightLightsFromMaterial } from '../surface/night-lights';
import { mountCloudSphere } from '../surface/clouds';
import { setShapeModelMap, setSurfaceMap } from './model-texture';

/** Pictures a host has put on a body. Each is a URL the browser can load, and
 *  what is left out is the map's own. */
export interface BodyAppearance {
	/** The surface map, drawn the way every body's is: equirectangular, east to
	 *  the right, with longitude 0 in the middle. */
	surface?: string;
	/** Lights on the unlit side, drawn where the map draws city lights. */
	night?: string;
	/** A layer over the surface, its alpha the cover. */
	clouds?: string;
}

/** What is on a body right now, and what the map's own was before it. */
export interface AppliedAppearance {
	/** The host owns the surface picture from the moment it is asked for,
	 *  before the picture itself has loaded, so nothing fetches one over it. */
	surfaceOwned?: boolean;
	surfaceUrl?: string;
	surfaceMap?: Texture;
	nightUrl?: string;
	nightMap?: Texture;
	/** The map's own night lights, kept to put back. */
	displacedNight?: Texture | null;
	cloudsUrl?: string;
	cloudsMap?: Texture;
	/** The map's own cloud picture, and the tiers it was choosing among. */
	displacedClouds?: Texture | null;
	displacedCloudTiers?: string[];
	displacedCloudFrames?: string[];
	/** The cloud layer was built for the override, so it goes with it. */
	ownCloudNode?: boolean;
	/** A load is in flight; a second one would race it. */
	loading?: boolean;
}

/**
 * The appearances one map has been given. Per map rather than per page: two
 * maps on one page are two sets of bodies, drawn from two renderers.
 */
export class BodyAppearances {
	private readonly wanted = new Map<string, BodyAppearance>();
	/** Bodies whose override has been taken off and not yet put back. */
	private readonly reverting = new Set<string>();

	/** Replace what a body looks like, whole: what the new appearance leaves
	 *  out goes back to the map's own picture. */
	set(id: string, appearance: BodyAppearance): void {
		const kept = { ...appearance };
		if (kept.surface === undefined && kept.night === undefined && kept.clouds === undefined) {
			this.wanted.delete(id);
		} else {
			this.wanted.set(id, kept);
		}
		this.reverting.add(id);
	}

	get(id: string): BodyAppearance | undefined {
		const appearance = this.wanted.get(id);
		return appearance && { ...appearance };
	}

	/** Whether the host owns this body's surface picture — what keeps the tier
	 *  loader from fetching one of the map's own over it. */
	ownsSurface(id: string): boolean {
		return this.wanted.get(id)?.surface !== undefined;
	}

	/** Per frame: put on what is missing, take off what is no longer asked
	 *  for. Nothing to do is the ordinary case and costs one test. */
	apply(bodyObjects: Map<string, BodyObjects>, textureLoader: TextureLoader): void {
		if (this.wanted.size === 0 && this.reverting.size === 0) return;
		for (const id of this.reverting) {
			const bo = bodyObjects.get(id);
			if (bo) revert(bo, this.wanted.get(id));
		}
		this.reverting.clear();
		for (const [id, appearance] of this.wanted) {
			const bo = bodyObjects.get(id);
			if (!bo?.mesh) continue;
			if (appearance.surface !== undefined) (bo.appearance ??= {}).surfaceOwned = true;
			void applyToBody(bo, appearance, textureLoader, () => this.wanted.get(id));
		}
	}
}

/** Take off whatever the new appearance no longer asks for, putting the map's
 *  own pictures back. */
function revert(bo: BodyObjects, appearance: BodyAppearance | undefined): void {
	const applied = bo.appearance;
	if (!applied || !bo.mesh) return;
	const material = bo.mesh.material as MeshStandardMaterial;

	if (applied.surfaceOwned && appearance?.surface === undefined) {
		applied.surfaceMap?.dispose();
		material.map = null;
		material.color.set(bodyMeshColor(bo.body.data));
		material.needsUpdate = true;
		if (bo.model) setShapeModelMap(bo.model, null, bodyMeshColor(bo.body.data));
		applied.surfaceOwned = undefined;
		applied.surfaceUrl = undefined;
		applied.surfaceMap = undefined;
		// No tier loaded any more, so the next LOD pass fetches the map's own.
		bo.textureTier = undefined;
	}

	if (applied.nightUrl !== undefined && appearance?.night === undefined) {
		const own = applied.displacedNight;
		applied.nightMap?.dispose();
		if (own) attachNightTexture(material, own);
		else disposeNightLightsFromMaterial(material);
		applied.nightUrl = undefined;
		applied.nightMap = undefined;
		applied.displacedNight = undefined;
	}

	if (applied.cloudsUrl !== undefined && appearance?.clouds === undefined) {
		applied.cloudsMap?.dispose();
		const node = bo.clouds;
		if (node && applied.ownCloudNode) {
			node.mesh.geometry.dispose();
			node.material.dispose();
			node.mesh.parent?.remove(node.mesh);
			bo.clouds = null;
		} else if (node) {
			node.material.map = applied.displacedClouds ?? null;
			node.material.needsUpdate = true;
			node.availableTiers = applied.displacedCloudTiers ?? [];
			node.availableFrames = applied.displacedCloudFrames ?? [];
		}
		applied.cloudsUrl = undefined;
		applied.cloudsMap = undefined;
		applied.displacedClouds = undefined;
		applied.ownCloudNode = undefined;
	}
}

/** Put the host's pictures on, and put back any the map has since taken off.
 *  `current` is what the host wants now: a picture that finishes loading after
 *  the host changed its mind is dropped, since the revert has already run and
 *  nothing would take it back off. */
async function applyToBody(
	bo: BodyObjects,
	appearance: BodyAppearance,
	textureLoader: TextureLoader,
	current: () => BodyAppearance | undefined
): Promise<void> {
	const applied = (bo.appearance ??= {});
	if (applied.loading) return;
	const material = liveMaterial(bo);
	if (!material) return;

	const wantsSurface =
		appearance.surface !== undefined &&
		(appearance.surface !== applied.surfaceUrl || material.map !== applied.surfaceMap);
	const wantsNight =
		appearance.night !== undefined &&
		(appearance.night !== applied.nightUrl || material.emissiveMap !== applied.nightMap);
	const wantsClouds =
		appearance.clouds !== undefined &&
		(appearance.clouds !== applied.cloudsUrl || bo.clouds?.material.map !== applied.cloudsMap);
	if (!wantsSurface && !wantsNight && !wantsClouds) return;

	applied.loading = true;
	try {
		if (wantsSurface) {
			const texture = await loadTexture(appearance.surface as string, textureLoader);
			if (current() !== appearance) return void texture?.dispose();
			const live = liveMaterial(bo);
			if (texture && live) {
				// Whatever was on the material goes out with it — a tier of the
				// map's own, or the host's own picture from before.
				setSurfaceMap(live, texture);
				if (bo.model) setShapeModelMap(bo.model, texture, bodyMeshColor(bo.body.data));
				applied.surfaceUrl = appearance.surface;
				applied.surfaceMap = texture;
			}
		}
		if (wantsNight) {
			const texture = await loadTexture(appearance.night as string, textureLoader);
			if (current() !== appearance) return void texture?.dispose();
			const live = liveMaterial(bo);
			if (texture && live) {
				applied.displacedNight ??= live.emissiveMap;
				attachNightTexture(live, texture);
				applied.nightUrl = appearance.night;
				applied.nightMap = texture;
			}
		}
		if (wantsClouds) {
			const texture = await loadTexture(appearance.clouds as string, textureLoader);
			if (current() !== appearance) return void texture?.dispose();
			if (texture && bo.mesh) applyClouds(bo, applied, texture, appearance.clouds as string);
		}
	} finally {
		applied.loading = false;
	}
}

/** The host's cloud picture on the body's own cloud layer, or on one built for
 *  it. Either way the layer is left with no tiers and no snapshots to choose
 *  among, so the LOD pass has nothing to swap it for. */
function applyClouds(
	bo: BodyObjects,
	applied: AppliedAppearance,
	texture: Texture,
	url: string
): void {
	let node = bo.clouds;
	if (!node) {
		if (!bo.mesh) return;
		node = mountCloudSphere(bo.mesh, bo.radiusScene, texture);
		bo.clouds = node;
		applied.ownCloudNode = true;
	} else {
		if (!applied.ownCloudNode) {
			applied.displacedClouds ??= node.material.map;
			applied.displacedCloudTiers ??= node.availableTiers;
			applied.displacedCloudFrames ??= node.availableFrames;
		}
		node.material.map = texture;
		node.material.needsUpdate = true;
	}
	node.availableTiers = [];
	node.availableFrames = [];
	applied.cloudsUrl = url;
	applied.cloudsMap = texture;
}

/** The body's material as it stands, or nothing while the body is unloaded:
 *  a picture that arrives after a teardown has nowhere to go. */
function liveMaterial(bo: BodyObjects): MeshStandardMaterial | null {
	return bo.mesh ? (bo.mesh.material as MeshStandardMaterial) : null;
}

async function loadTexture(url: string, textureLoader: TextureLoader): Promise<Texture | null> {
	try {
		const texture = await new Promise<Texture>((resolve, reject) => {
			textureLoader.load(url, resolve, undefined, reject);
		});
		texture.colorSpace = SRGBColorSpace;
		return texture;
	} catch (err) {
		console.warn(`spacemap: could not load the picture at ${url}:`, err);
		return null;
	}
}
