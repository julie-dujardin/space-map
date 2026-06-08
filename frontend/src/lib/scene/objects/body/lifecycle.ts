import {
	CanvasTexture,
	Group,
	type Material,
	Mesh,
	MeshStandardMaterial,
	type Object3D,
	Scene,
	SphereGeometry
} from 'three';
import { resolveBodyColor } from '$lib/utils';
import { MINOR_PROMOTED_IDS } from '$lib/constants';
import { kmToScene } from '$lib/math/units';
import { ObjectType, effectiveRadiusKm, isAsteroid, type PositionedBody } from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { createLabel, getLabelVariant } from '../../label/factory';
import { attachCanvasForwarders } from '../../label/forward';
import { buildStarExtras, makeStarSurfaceMaterial, type StarExtras } from '../sun';
import { ATMOSPHERE_PARAMS, buildAtmosphereNode, type AtmosphereNode } from '../surface/atmosphere';
import { attachEclipseShadowToBody, type EclipseSelfUniforms } from '../surface/eclipse-shadow';
import { unloadBodyModel } from './model';
import type { BodyObjects } from '../../types';

export function disposeMaterial(mat: Material | Material[]): void {
	if (Array.isArray(mat)) for (const m of mat) m.dispose();
	else mat.dispose();
}

const STAR_SPHERE_SEGMENTS = 96;
const BODY_SPHERE_SEGMENTS = 64;

export function buildMajorBodies(
	bodies: PositionedBody[],
	scene: Scene,
	clickables: Mesh[],
	meshToBody: Map<Mesh, PositionedBody>,
	bodyObjects: Map<string, BodyObjects>,
	circleTexture: CanvasTexture,
	rendererElement: HTMLCanvasElement,
	handleFocus: (body: PositionedBody) => void,
	onHoverChange?: (id: string, hovered: boolean) => void,
	/** Force halo-only + minor treatment for these ids regardless of object type.
	 *  Used by group half-promotion so otherwise-meshy SPACECRAFT entries render
	 *  as a collapsed halo + on-hover label, no trail. */
	halfPromoteIds?: ReadonlySet<string>
): void {
	for (const body of bodies) {
		const id = body.data.id;
		const isHalfPromoted = halfPromoteIds?.has(id) ?? false;
		// Halo-only types render as label + halo without a sphere mesh; trails are
		// built separately. Per-frame loops skip entries with mesh === null.
		const t = body.data.objectType;
		const isVirtual =
			isHalfPromoted ||
			t === ObjectType.BARYCENTER ||
			t === ObjectType.LAGRANGE_POINT ||
			t === ObjectType.COMET ||
			isAsteroid(t) ||
			body.data.orbitalSource === OrbitalSource.SPICE_PROBE;
		const color = resolveBodyColor(body.data);
		const radius = kmToScene(effectiveRadiusKm(body.data));
		const isStar = t === ObjectType.STAR;

		const group = new Group();
		// repositionAll() applies the focus-relative offset each frame.
		group.position.set(0, 0, 0);

		let mesh: Mesh | null = null;
		let starExtras: StarExtras | null = null;
		let eclipseShadow: EclipseSelfUniforms | null = null;
		let atmosphere: AtmosphereNode | null = null;
		const extraObjects: Object3D[] = [];
		if (!isVirtual) {
			if (isStar) {
				starExtras = buildStarExtras(scene, radius, color, circleTexture);
				extraObjects.push(starExtras.light, starExtras.corona, starExtras.starPoint);
			}

			const segments = isStar ? STAR_SPHERE_SEGMENTS : BODY_SPHERE_SEGMENTS;
			const geometry = new SphereGeometry(radius, segments, segments);
			const material = isStar ? makeStarSurfaceMaterial() : new MeshStandardMaterial({ color });
			mesh = new Mesh(geometry, material);
			if (!isStar) {
				// Body-on-body shadows are analytical (fragment shader); shadow map unused.
				eclipseShadow = attachEclipseShadowToBody(material as MeshStandardMaterial);
			}
			scene.add(mesh);
			extraObjects.push(mesh);

			clickables.push(mesh);
			meshToBody.set(mesh, body);

			// Scattering shell, kept centred on the body via extraObjects.
			const atmoParams = isStar ? undefined : ATMOSPHERE_PARAMS[id];
			if (atmoParams) {
				atmosphere = buildAtmosphereNode(atmoParams, radius, effectiveRadiusKm(body.data));
				scene.add(atmosphere.mesh);
				extraObjects.push(atmosphere.mesh);
			}
		}

		const variant = getLabelVariant(body);
		const isLarge = isStar || t === ObjectType.PLANET;
		// Curated frontend list ∪ data-driven `m` flag for designation-only moons.
		const isMinor = isHalfPromoted || MINOR_PROMOTED_IDS.has(id) || body.data.isMinor === true;
		const label = createLabel(
			color,
			body.data.name ?? '',
			variant,
			() => handleFocus(body),
			isLarge,
			onHoverChange ? (hovered) => onHoverChange(id, hovered) : undefined,
			isMinor
		);
		if (label) {
			attachCanvasForwarders(label.element, rendererElement);
			group.add(label);
		}

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
			loadingEl: null,
			extraObjects,
			corona: starExtras?.corona ?? null,
			starPoint: starExtras?.starPoint ?? null,
			// Trail is built later via buildTrails() to defer 100K+ Kepler solves.
			trail: null,
			radiusScene: radius,
			cachedDist: 0,
			currentSegments: isVirtual ? undefined : isStar ? STAR_SPHERE_SEGMENTS : BODY_SPHERE_SEGMENTS,
			isMinor,
			rings: null,
			clouds: null,
			atmosphere,
			specularMap: null,
			emissiveMap: null,
			eclipseShadow,
			nomenclatureLabels: null,
			model: null
		});
	}
}

/**
 * True for body types that auto-promote to a halo+label entry but should swap
 * to a full sphere mesh once focused (and drop back to halo-only on un-focus).
 * Barycenters and Lagrange points are halo-only too, but have no physical body
 * so they never upgrade.
 */
export function isMeshUpgradable(body: PositionedBody): boolean {
	const t = body.data.objectType;
	return (
		t === ObjectType.COMET || isAsteroid(t) || body.data.orbitalSource === OrbitalSource.SPICE_PROBE
	);
}

/**
 * Add the sphere mesh (+ atmosphere, eclipse shadow, clickable registration) to
 * an existing halo-only {@link BodyObjects} entry. No-op if a mesh already
 * exists. Caller re-runs `buildTrails` to pick up the trail for non-probe types
 * whose halo-only state had no trail.
 */
export function upgradeBodyMesh(
	bo: BodyObjects,
	scene: Scene,
	clickables: Mesh[],
	meshToBody: Map<Mesh, PositionedBody>
): void {
	if (bo.mesh !== null) return;
	const { body, radiusScene } = bo;
	const color = resolveBodyColor(body.data);
	const segments = BODY_SPHERE_SEGMENTS;
	const geometry = new SphereGeometry(radiusScene, segments, segments);
	const material = new MeshStandardMaterial({ color });
	const mesh = new Mesh(geometry, material);
	scene.add(mesh);
	bo.mesh = mesh;
	bo.extraObjects.push(mesh);
	clickables.push(mesh);
	meshToBody.set(mesh, body);
	bo.eclipseShadow = attachEclipseShadowToBody(material);
	bo.currentSegments = segments;

	const atmoParams = ATMOSPHERE_PARAMS[body.data.id];
	if (atmoParams) {
		bo.atmosphere = buildAtmosphereNode(atmoParams, radiusScene, effectiveRadiusKm(body.data));
		scene.add(bo.atmosphere.mesh);
		bo.extraObjects.push(bo.atmosphere.mesh);
	}
}

/**
 * Reverse of {@link upgradeBodyMesh}: dispose the sphere mesh, atmosphere, and
 * eclipse shadow; for non-probe types also dispose the trail so the body
 * reverts to a labelled halo only. Probes keep their trail (their halo-only
 * mode is "halo + trail, no mesh").
 */
export function downgradeBodyMesh(
	bo: BodyObjects,
	scene: Scene,
	clickables: Mesh[],
	meshToBody: Map<Mesh, PositionedBody>
): void {
	// 3D model lives in the overlay scene — dispose first to release its
	// textures + geometry before the sphere teardown below.
	unloadBodyModel(bo);
	const mesh = bo.mesh;
	if (mesh) {
		scene.remove(mesh);
		mesh.geometry.dispose();
		disposeMaterial(mesh.material);
		const idx = clickables.indexOf(mesh);
		if (idx >= 0) clickables.splice(idx, 1);
		meshToBody.delete(mesh);
		const extraIdx = bo.extraObjects.indexOf(mesh);
		if (extraIdx >= 0) bo.extraObjects.splice(extraIdx, 1);
		bo.mesh = null;
		bo.currentSegments = undefined;
		bo.eclipseShadow = null;
		// The new mesh on re-upgrade starts with identity scale, so the
		// triaxial scale needs to be re-applied. (`bo.radiusScene` keeps its
		// bumped value — the next sphere is built at that size, and the
		// radii application below produces the right (a, b, c) regardless.)
		bo.radiiApplied = false;
	}

	if (bo.atmosphere) {
		const atmoMesh = bo.atmosphere.mesh;
		scene.remove(atmoMesh);
		const ai = bo.extraObjects.indexOf(atmoMesh);
		if (ai >= 0) bo.extraObjects.splice(ai, 1);
		atmoMesh.geometry.dispose();
		disposeMaterial(atmoMesh.material);
		bo.atmosphere = null;
	}

	const isProbe = bo.body.data.orbitalSource === OrbitalSource.SPICE_PROBE;
	if (bo.trail && !isProbe) {
		scene.remove(bo.trail);
		bo.trail.geometry.dispose();
		disposeMaterial(bo.trail.material);
		bo.trail = null;
	}
}
