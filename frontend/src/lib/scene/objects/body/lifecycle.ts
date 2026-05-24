import {
	CanvasTexture,
	Group,
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
import { buildStarExtras, makeStarSurfaceMaterial, type StarExtras } from '../sun';
import { ATMOSPHERE_PARAMS, buildAtmosphereNode, type AtmosphereNode } from '../atmosphere';
import { attachEclipseShadowToBody, type EclipseSelfUniforms } from '../eclipse-shadow';
import type { BodyObjects } from '../../types';

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
		// "Halo-only" types render as a label + halo with no sphere mesh and
		// (handled by `buildTrails` below) no trail: barycenters and
		// Lagrange points have no physical body, and asteroids/comets/probes
		// are too small to be visually meaningful at planetary scale — the
		// halo carries the name + click target. Per-frame iteration loops
		// (visibility, sphere/texture LOD, ring shaders) skip entries with
		// `mesh === null`, so this keeps the body's slot in `bodyObjects`
		// effectively free.
		const t = body.data.objectType;
		const isVirtual =
			t === ObjectType.BARYCENTER ||
			t === ObjectType.LAGRANGE_POINT ||
			t === ObjectType.COMET ||
			isAsteroid(t) ||
			body.data.orbitalSource === OrbitalSource.SPICE_PROBE;
		const color = resolveBodyColor(body.data);
		const radius = kmToScene(effectiveRadiusKm(body.data));
		const isStar = t === ObjectType.STAR;

		const group = new Group();
		// Position set to origin — repositionAll() applies focus-relative offset each frame
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

			const segments = isStar ? 96 : 64;
			const geometry = new SphereGeometry(radius, segments, segments);
			const material = isStar ? makeStarSurfaceMaterial() : new MeshStandardMaterial({ color });
			mesh = new Mesh(geometry, material);
			if (!isStar) {
				// Body-on-body shadows are computed analytically by the
				// eclipse-shadow path inside this material's fragment shader,
				// so the directional shadow map isn't involved — no cast/receive
				// flags needed.
				eclipseShadow = attachEclipseShadowToBody(material as MeshStandardMaterial);
			}
			scene.add(mesh);
			extraObjects.push(mesh);

			clickables.push(mesh);
			meshToBody.set(mesh, body);

			// Atmospheric-scattering shell, for bodies that have one. A sibling
			// scene object kept at the body's centre by `repositionBodies`
			// (hence the `extraObjects` membership); its sun direction is
			// refreshed each frame in the renderer.
			const atmoParams = isStar ? undefined : ATMOSPHERE_PARAMS[id];
			if (atmoParams) {
				atmosphere = buildAtmosphereNode(atmoParams, radius, effectiveRadiusKm(body.data));
				scene.add(atmosphere.mesh);
				extraObjects.push(atmosphere.mesh);
			}
		}

		// CSS2D label
		const variant = getLabelVariant(body);
		const isLarge = isStar || t === ObjectType.PLANET;
		// Two minor sources: the curated barycenter/asteroid list (frontend-only),
		// and the data-driven `m` flag the labels file ships for designation-only
		// moons (e.g. naif-65289/S2020 S48). Both render the same way — collapsed
		// halo by default, expand-and-name on hover.
		const isMinor = MINOR_PROMOTED_IDS.has(id) || body.data.isMinor === true;
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

		// Trail — built later in buildTrails() to defer 100K+ Kepler solves
		const trail = null;

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
			corona: starExtras?.corona ?? null,
			starPoint: starExtras?.starPoint ?? null,
			trail,
			radiusScene: radius,
			cachedDist: 0,
			currentSegments: isVirtual ? undefined : isStar ? 96 : 64,
			isMinor,
			rings: null,
			clouds: null,
			atmosphere,
			specularMap: null,
			eclipseShadow
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
	const segments = 64;
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
	const mesh = bo.mesh;
	if (mesh) {
		scene.remove(mesh);
		mesh.geometry.dispose();
		const mat = mesh.material;
		if (Array.isArray(mat)) for (const m of mat) m.dispose();
		else mat.dispose();
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
		const m = atmoMesh.material;
		if (Array.isArray(m)) for (const mm of m) mm.dispose();
		else m.dispose();
		bo.atmosphere = null;
	}

	const isProbe = bo.body.data.orbitalSource === OrbitalSource.SPICE_PROBE;
	if (bo.trail && !isProbe) {
		scene.remove(bo.trail);
		bo.trail.geometry.dispose();
		const lm = bo.trail.material;
		if (Array.isArray(lm)) for (const mm of lm) mm.dispose();
		else lm.dispose();
		bo.trail = null;
	}
}
