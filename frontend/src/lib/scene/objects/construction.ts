import {
	CanvasTexture,
	Group,
	Mesh,
	MeshBasicMaterial,
	MeshStandardMaterial,
	type Object3D,
	Points,
	PointLight,
	PointsMaterial,
	Scene,
	SphereGeometry,
	type Sprite
} from 'three';
import type { Lensflare } from 'three/addons/objects/Lensflare.js';
import { resolveBodyColor } from '$lib/utils';
import { kmToScene } from '$lib/math/units';
import { applyOrientation } from '$lib/math/orientation';
import { getNutPrecAngles, ownerIdFor } from '$lib/fetch/nut-prec-angles';
import { ObjectType, effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { DATA_BASE } from '$lib/fetch/data-base';
import { TextureLoader, type Texture } from 'three';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import { createLabel, getLabelVariant } from '../label/factory';
import {
	makeCircleTexture,
	makeOrbitLine,
	makePointCloud,
	makeStarGlow,
	makeStarPoint
} from './builders';
import type { BodyObjects } from '../types';

function excludePromoted(bodies: PositionedBody[], promotedIds?: Set<string>): PositionedBody[] {
	if (!promotedIds || promotedIds.size === 0) return bodies;
	return bodies.filter((b) => !promotedIds.has(b.data.id));
}

export function buildMajorBodies(
	bodies: PositionedBody[],
	scene: Scene,
	clickables: Mesh[],
	meshToBody: Map<Mesh, PositionedBody>,
	bodyObjects: Map<string, BodyObjects>,
	circleTexture: CanvasTexture,
	rendererElement: HTMLCanvasElement,
	handleFocus: (body: PositionedBody) => void,
	onHoverChange?: (id: string, hovered: boolean) => void
): void {
	for (const body of bodies) {
		const id = body.data.id;
		const isVirtual =
			body.data.objectType === ObjectType.BARYCENTER ||
			body.data.objectType === ObjectType.LAGRANGE_POINT;
		const color = resolveBodyColor(body.data);
		const radius = kmToScene(effectiveRadiusKm(body.data));
		const isStar = body.data.objectType === ObjectType.STAR;

		const group = new Group();
		// Position set to origin — repositionAll() applies focus-relative offset each frame
		group.position.set(0, 0, 0);

		let mesh: Mesh | null = null;
		let starPoint: Points | null = null;
		let coronaSprite: Sprite | null = null;
		let lensflareObj: Lensflare | null = null;
		const extraObjects: Object3D[] = [];
		if (!isVirtual) {
			if (isStar) {
				const light = new PointLight(0xffffff, 2, 0, 0);
				scene.add(light);
				const { corona, lensflare } = makeStarGlow(radius, color);
				coronaSprite = corona;
				lensflareObj = lensflare;
				scene.add(corona);
				scene.add(lensflare);
				starPoint = makeStarPoint(color, circleTexture);
				scene.add(starPoint);
				extraObjects.push(light, corona, lensflare, starPoint);
			}

			const segments = isStar ? 96 : 64;
			const geometry = new SphereGeometry(radius, segments, segments);
			const material = isStar
				? new MeshBasicMaterial({ color })
				: new MeshStandardMaterial({ color });
			mesh = new Mesh(geometry, material);
			if (!isStar) {
				mesh.receiveShadow = true;
				const canCast =
					body.data.objectType === ObjectType.PLANET ||
					body.data.objectType === ObjectType.DWARF_PLANET ||
					body.data.objectType === ObjectType.MOON;
				mesh.castShadow = canCast;
			}
			scene.add(mesh);
			extraObjects.push(mesh);

			clickables.push(mesh);
			meshToBody.set(mesh, body);
		}

		// CSS2D label
		const variant = getLabelVariant(body);
		const isLarge = isStar || body.data.objectType === ObjectType.PLANET;
		const label = createLabel(
			color,
			body.data.name ?? '',
			variant,
			() => handleFocus(body),
			isLarge,
			onHoverChange ? (hovered) => onHoverChange(id, hovered) : undefined
		);
		if (label) {
			// Forward wheel events so OrbitControls zoom still works when hovering a label
			label.element.addEventListener(
				'wheel',
				(e: Event) => {
					const we = e as WheelEvent;
					rendererElement.dispatchEvent(
						new WheelEvent('wheel', {
							deltaY: we.deltaY,
							deltaMode: we.deltaMode,
							bubbles: true,
							cancelable: true
						})
					);
					we.preventDefault();
				},
				{ passive: false }
			);
			// Forward pointer events so OrbitControls can pan/pinch from labels.
			// Defer until pointer moves >3px so taps still fire click on
			// the label. Once forwarded, setPointerCapture on the canvas steals
			// subsequent events, which suppresses the label's click
			label.element.addEventListener('pointerdown', (e: PointerEvent) => {
				const downX = e.clientX;
				const downY = e.clientY;
				const savedDown = e; // keep the original event for deferred forwarding
				const onMove = (me: PointerEvent) => {
					const dx = me.clientX - downX;
					const dy = me.clientY - downY;
					if (dx * dx + dy * dy > 9) {
						cleanup();
						rendererElement.dispatchEvent(new PointerEvent('pointerdown', savedDown));
						rendererElement.dispatchEvent(new PointerEvent('pointermove', me));
					}
				};
				const onUp = () => cleanup();
				const cleanup = () => {
					window.removeEventListener('pointermove', onMove);
					window.removeEventListener('pointerup', onUp);
				};
				window.addEventListener('pointermove', onMove);
				window.addEventListener('pointerup', onUp);
			});
			group.add(label);
		}

		// Orbit line — built later in buildOrbitLines() to defer 100K+ Kepler solves
		const orbitLine = null;

		scene.add(group);
		const labelHalo = label ? (label.element.firstElementChild as HTMLElement) : null;
		if (labelHalo) {
			labelHalo.dataset.origBorder = labelHalo.style.border;
		}
		bodyObjects.set(id, {
			body,
			group,
			mesh,
			label,
			labelHalo,
			extraObjects,
			corona: coronaSprite,
			lensflare: lensflareObj,
			starPoint,
			orbitLine,
			radiusScene: radius,
			cachedDist: 0
		});
	}
}

export function buildOrbitLines(
	bodyObjects: Map<string, BodyObjects>,
	scene: Scene,
	basisPos: [number, number, number] = [0, 0, 0],
	jd?: number
): void {
	for (const [, bo] of bodyObjects) {
		if (bo.orbitLine !== null) continue;
		const { body } = bo;
		if (!body.orbitElements || body.data.objectType === ObjectType.STAR) continue;
		const color = resolveBodyColor(body.data);
		const line = makeOrbitLine(body, color, basisPos, jd);
		scene.add(line);
		bo.orbitLine = line;
	}
}

export function buildPointClouds(
	ctx: ContextManager,
	scene: Scene,
	circleTexture: CanvasTexture,
	basisPos: [number, number, number] = [0, 0, 0],
	promotedIds?: Set<string>
): {
	asteroidPoints: Map<string, Points>;
	spacecraftPoints: Map<string, Points>;
	moonPoints: Map<string, Points>;
} {
	const asteroidPoints = new Map<string, Points>();
	const spacecraftPoints = new Map<string, Points>();
	const moonPoints = new Map<string, Points>();

	// Asteroid point clouds (one per zone)
	for (const [zone, bodies] of ctx.asteroidBodiesByZone) {
		const filtered = excludePromoted(bodies, promotedIds);
		if (filtered.length > 0) {
			const pts = makePointCloud(
				filtered,
				circleTexture,
				resolveBodyColor(filtered[0].data),
				basisPos
			);
			asteroidPoints.set(zone, pts);
			scene.add(pts);
		}
	}

	// Spacecraft point clouds (one per parent body)
	for (const [groupParentId, bodies] of ctx.spacecraftByParent.entries()) {
		const filtered = excludePromoted(bodies, promotedIds);
		if (filtered.length === 0) continue;
		const points = makePointCloud(
			filtered,
			circleTexture,
			resolveBodyColor(filtered[0].data),
			basisPos
		);
		spacecraftPoints.set(groupParentId, points);
		scene.add(points);
	}

	// Moon point clouds (one per parent body, initially hidden)
	const moonsByParent = new Map<string, PositionedBody[]>();
	for (const body of ctx.majorBodies) {
		if (body.data.objectType === ObjectType.MOON) {
			const list = moonsByParent.get(body.data.parentId) ?? [];
			list.push(body);
			moonsByParent.set(body.data.parentId, list);
		}
	}
	for (const [parentId, moons] of moonsByParent) {
		const pts = makePointCloud(moons, circleTexture, resolveBodyColor(moons[0].data), basisPos);
		const mat = pts.material as PointsMaterial;
		// Render moon dots in the opaque pass with alpha-tested cutout. Lets the
		// body mesh occlude its own dot cleanly via depth test once the camera
		// is close enough that the mesh fills the sprite footprint — without
		// this, the transparent-pass dot punches through the mesh at center.
		mat.transparent = false;
		mat.alphaTest = 0.5;
		mat.depthTest = true;
		mat.depthWrite = true;
		pts.visible = false;
		moonPoints.set(parentId, pts);
		scene.add(pts);
	}

	return { asteroidPoints, spacecraftPoints, moonPoints };
}

/**
 * Load a texture tier and swap it onto the body's material, disposing the
 * prior map. Sets `textureLoading` while in flight and `textureTier` on success.
 */
async function swapBodyTexture(
	bo: BodyObjects,
	tier: string,
	textureLoader: TextureLoader
): Promise<void> {
	if (!bo.mesh) return;
	const fileId = bo.body.data.id;
	bo.textureLoading = true;
	try {
		const texture = await new Promise<Texture>((resolve, reject) => {
			textureLoader.load(
				`${DATA_BASE}/v1/textures/${fileId}/${tier}.webp`,
				resolve,
				undefined,
				reject
			);
		});
		const material = bo.mesh.material as MeshStandardMaterial;
		material.map?.dispose();
		material.map = texture;
		material.color.set(0xffffff);
		material.needsUpdate = true;
		bo.textureTier = tier;
	} catch (err) {
		console.warn(`Failed to load ${tier} texture for ${fileId}:`, err);
	} finally {
		bo.textureLoading = false;
	}
}

/**
 * Initial low-tier texture load, used when focusing a body that may not be
 * part of a pre-declared system (the system-metadata path handles the rest).
 * Also forwards the texture attribution to `ctx` so the bar/popover can
 * credit standalone bodies (e.g. Bennu, Ceres) the same way it credits bodies
 * registered via loadSystemData.
 */
export async function loadBodyTexture(
	bo: BodyObjects,
	textureLoader: TextureLoader,
	objectFileFlag = 1,
	ctx?: ContextManager
): Promise<void> {
	if (objectFileFlag === 0) return;
	if (bo.textureTier || bo.textureLoading) return;
	const detail = await fetchObjectDetail(bo.body.data.id, objectFileFlag);
	if (!detail.global?.map_texture_available) return;
	if (ctx && detail.global.texture) {
		// Standalones aren't tied to a planetary system barycenter; key the
		// credit on the body itself so the bar/popover can match it against
		// the focused body id.
		const bodyId = bo.body.data.id;
		ctx.registerTextureCredit({
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
	bo.availableTiers ??= ['low', 'medium', 'high'];
	await swapBodyTexture(bo, 'low', textureLoader);
}

/**
 * Load a specific texture tier for a body and swap it onto its material.
 * No-op if the tier is already loaded, unavailable, or another load is in flight.
 */
export async function loadBodyTextureTier(
	bo: BodyObjects,
	tier: string,
	textureLoader: TextureLoader
): Promise<void> {
	if (bo.textureTier === tier || bo.textureLoading) return;
	if (!bo.availableTiers?.includes(tier)) return;
	await swapBodyTexture(bo, tier, textureLoader);
}

interface SystemBodyMeta {
	tiers?: string[];
	/** Attribution block — matches `export/systems.py::texture_attribution`. */
	texture?: {
		source: string;
		organisation: string;
		type: string;
		attribution?: string;
		description?: string;
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
}

/**
 * Fetch system metadata (textures + orientation) and apply to all bodies in that system.
 * The metadata file is keyed by barycenter ID (e.g. naif-3, naif-5).
 */
export async function loadSystemData(
	barycenterId: string,
	bodyObjects: Map<string, BodyObjects>,
	textureLoader: TextureLoader,
	currentJd: number,
	ctx?: ContextManager
): Promise<void> {
	let meta: Record<string, SystemBodyMeta>;
	try {
		const resp = await fetch(`${DATA_BASE}/v1/systems/${barycenterId}.json`);
		if (!resp.ok) return;
		meta = await resp.json();
	} catch {
		return;
	}

	const promises: Promise<void>[] = [];
	for (const [bodyId, bodyMeta] of Object.entries(meta)) {
		if (ctx && bodyMeta.texture) {
			ctx.registerTextureCredit({
				bodyId,
				systemId: barycenterId,
				source: bodyMeta.texture.source,
				organisation: bodyMeta.texture.organisation,
				type: bodyMeta.texture.type,
				attribution: bodyMeta.texture.attribution,
				description: bodyMeta.texture.description
			});
		}
		const bo = bodyObjects.get(bodyId);
		if (!bo?.mesh) continue;

		// Apply orientation (axial tilt + spin) and cache for per-frame re-application.
		if (bodyMeta.orientation) {
			bo.orientation = bodyMeta.orientation;

			// Resolve per-body nutation/precession by joining coefficients with the
			// system-shared angles (one IAU table per planetary system).
			if (bodyMeta.nut_prec) {
				const naifMatch = bodyId.match(/^naif-(-?\d+)$/);
				const naifId = naifMatch ? parseInt(naifMatch[1], 10) : null;
				const angles = naifId !== null ? getNutPrecAngles(ownerIdFor(naifId)) : undefined;
				if (angles) {
					bo.nutPrec = { ...bodyMeta.nut_prec, angles };
				}
			}

			applyOrientation(bo.mesh, bodyMeta.orientation, currentJd, bo.nutPrec);
		}

		// Apply triaxial flattening. applyOrientation puts the body's pole on
		// local +Y and the ascending node on local +X, so SPICE (X, Y, Z)
		// maps to mesh local (X, Z, Y).
		if (bodyMeta.radii && bo.radiusScene > 0) {
			const { a, b, c } = bodyMeta.radii;
			const s = kmToScene(1) / bo.radiusScene;
			bo.mesh.scale.set(a * s, c * s, b * s);
			// Replace the scalar radiusScene (sourced from SBDB/Wikidata, used
			// for halo visibility, label placement, texture LOD and screen
			// occlusion) with the rendered ellipsoid's largest extent so those
			// screen-size checks match what the user sees.
			bo.radiusScene = kmToScene(Math.max(a, b, c));
		}

		// Record available tiers and load the base `low` tier if no texture is
		// loaded yet. Higher tiers are loaded on-demand by the per-frame LOD
		// update based on screen size. Skip if a tier is already loaded to avoid
		// downgrading (e.g. high → low → re-upgrade) on repeated system visits.
		if (bodyMeta.tiers?.length) {
			bo.availableTiers = bodyMeta.tiers;
			if (!bo.textureTier) {
				promises.push(loadBodyTextureTier(bo, 'low', textureLoader));
			}
		}
	}
	await Promise.allSettled(promises);
}

export { makeCircleTexture };
