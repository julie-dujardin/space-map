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
import { bodyMeshColor, resolveBodyColor } from '$lib/utils';
import { MINOR_PROMOTED_IDS } from '$lib/constants';
import { kmToScene } from '$lib/math/units';
import {
	ObjectType,
	effectiveRadiusKm,
	isAsteroid,
	isNaturalBody,
	type PositionedBody
} from '$lib/types/objects';
import { OrbitalSource } from '$lib/fetch/position/format';
import { createLabel, getLabelVariant } from '../../label/factory';
import { bodyHref } from '$lib/state/url';
import { attachCanvasForwarders } from '../../label/forward';
import { buildStarExtras, makeStarSurfaceMaterial, type StarExtras } from '../sun';
import { getAtmosphereParams } from '$lib/fetch/atmospheres';
import { buildAtmosphereNode, type AtmosphereNode } from '../surface/atmosphere';
import { attachEclipseShadowToBody, type EclipseSelfUniforms } from '../surface/eclipse-shadow';
import {
	attachSunTransmittanceToBody,
	type SunTransmittanceUniforms
} from '../surface/sun-transmittance';
import { detachSelfShadow } from '../surface/self-shadow';
import { isModelBearing, unloadBodyModel } from './model';
import type { BodyObjects } from '../../types';

export function disposeMaterial(mat: Material | Material[]): void {
	if (Array.isArray(mat)) for (const m of mat) m.dispose();
	else mat.dispose();
}

const STAR_SPHERE_SEGMENTS = 96;
/** Initial mesh detail — deliberately the sphere-LOD floor. `updateSphereLOD`
 *  up-steps geometry once a body covers real screen space; building all ~200
 *  bodies at 64 segments cost 150ms+ of startup. */
const BODY_SPHERE_SEGMENTS = 24;

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
	/** Force halo-only + minor treatment for these ids, so group half-promotion
	 *  can collapse otherwise-meshy SPACECRAFT entries to halo + on-hover label, no trail. */
	halfPromoteIds?: ReadonlySet<string>
): void {
	for (const body of bodies) {
		const id = body.data.id;
		const isHalfPromoted = halfPromoteIds?.has(id) ?? false;
		// Halo-only types render as label + halo, no sphere; per-frame loops
		// skip entries with mesh === null. Trails are built separately.
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
		// No measured size → halo only, no fallback sphere (model-bearing types
		// use the overlay instead, so an unknown radius there is expected).
		const modelBearing = isModelBearing(body);
		const radiusKnown = Number.isFinite(body.data.radiusKm) && body.data.radiusKm > 0;
		const noPhysical: 'model' | 'radius' | undefined =
			!modelBearing && isNaturalBody(t) && !radiusKnown ? 'radius' : undefined;

		const group = new Group();
		// repositionAll() applies the focus-relative offset each frame.
		group.position.set(0, 0, 0);

		let mesh: Mesh | null = null;
		let starExtras: StarExtras | null = null;
		let eclipseShadow: EclipseSelfUniforms | null = null;
		let atmosphere: AtmosphereNode | null = null;
		let sunTint: SunTransmittanceUniforms[] | undefined;
		const extraObjects: Object3D[] = [];
		if (!isVirtual && !noPhysical) {
			if (isStar) {
				starExtras = buildStarExtras(scene, radius, color, circleTexture);
				extraObjects.push(starExtras.light, starExtras.corona, starExtras.starPoint);
			}

			const segments = isStar ? STAR_SPHERE_SEGMENTS : BODY_SPHERE_SEGMENTS;
			const geometry = new SphereGeometry(radius, segments, segments);
			// Sphere uses the per-body export colour or neutral white; `color`
			// (per-type) stays for star glow + halos, so the UI reads as type-level.
			const material = isStar
				? makeStarSurfaceMaterial()
				: new MeshStandardMaterial({ color: bodyMeshColor(body.data) });
			mesh = new Mesh(geometry, material);
			// Model-bearing types use the model overlay — hide the sphere so it can't flash.
			if (modelBearing) mesh.visible = false;
			if (!isStar) {
				// Body-on-body shadows are analytical (fragment shader); shadow map unused.
				eclipseShadow = attachEclipseShadowToBody(material as MeshStandardMaterial);
			}
			scene.add(mesh);
			extraObjects.push(mesh);

			clickables.push(mesh);
			meshToBody.set(mesh, body);

			// Scattering shell, kept centred on the body via extraObjects.
			const atmoParams = isStar ? undefined : getAtmosphereParams(id);
			if (atmoParams) {
				atmosphere = buildAtmosphereNode(atmoParams, radius, effectiveRadiusKm(body.data));
				scene.add(atmosphere.mesh);
				extraObjects.push(atmosphere.mesh);
				if (eclipseShadow) {
					sunTint = [
						attachSunTransmittanceToBody(
							material as MeshStandardMaterial,
							atmoParams,
							radius,
							effectiveRadiusKm(body.data),
							eclipseShadow,
							atmosphere
						)
					];
				}
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
			bodyHref(id, body.data.name ?? ''),
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
			labelSub: null,
			loadingEl: null,
			extraObjects,
			corona: starExtras?.corona ?? null,
			starPoint: starExtras?.starPoint ?? null,
			// Trail is built later via buildTrails() to defer 100K+ Kepler solves.
			trail: null,
			radiusScene: radius,
			cachedDist: 0,
			currentSegments:
				isVirtual || noPhysical ? undefined : isStar ? STAR_SPHERE_SEGMENTS : BODY_SPHERE_SEGMENTS,
			isMinor,
			noPhysical,
			noteEl: null,
			rings: [],
			clouds: null,
			atmosphere,
			sunTint,
			specularMap: null,
			emissiveMap: null,
			displacementMap: null,
			selfShadow: null,
			eclipseShadow,
			nomenclatureLabels: null,
			model: null
		});
	}
}

/**
 * True for types that auto-promote to halo+label but swap to a full sphere on
 * focus (and back on un-focus). Barycenters/Lagrange points are halo-only too
 * but have no physical body, so they never upgrade.
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
 * exists. Caller re-runs `buildTrails` for non-probe types that had no trail.
 */
export function upgradeBodyMesh(
	bo: BodyObjects,
	scene: Scene,
	clickables: Mesh[],
	meshToBody: Map<Mesh, PositionedBody>
): void {
	if (bo.mesh !== null) return;
	const { body, radiusScene } = bo;
	bo.focusUpgraded = true;
	const modelBearing = isModelBearing(body);
	// No measured size → stay halo-only; nothing to build.
	if (!modelBearing && !(Number.isFinite(body.data.radiusKm) && body.data.radiusKm > 0)) {
		bo.noPhysical = 'radius';
		return;
	}
	// Per-body export colour, else neutral white — the per-type tint stays
	// UI-only, on point clouds/halos/trails.
	const color = bodyMeshColor(body.data);
	const segments = BODY_SPHERE_SEGMENTS;
	const geometry = new SphereGeometry(radiusScene, segments, segments);
	const material = new MeshStandardMaterial({ color });
	const mesh = new Mesh(geometry, material);
	// Probes are model-bearing — hide the sphere.
	if (modelBearing) mesh.visible = false;
	scene.add(mesh);
	bo.mesh = mesh;
	bo.extraObjects.push(mesh);
	clickables.push(mesh);
	meshToBody.set(mesh, body);
	bo.eclipseShadow = attachEclipseShadowToBody(material);
	bo.currentSegments = segments;

	const atmoParams = getAtmosphereParams(body.data.id);
	if (atmoParams) {
		bo.atmosphere = buildAtmosphereNode(atmoParams, radiusScene, effectiveRadiusKm(body.data));
		scene.add(bo.atmosphere.mesh);
		bo.extraObjects.push(bo.atmosphere.mesh);
		bo.sunTint = [
			attachSunTransmittanceToBody(
				material,
				atmoParams,
				radiusScene,
				effectiveRadiusKm(body.data),
				bo.eclipseShadow,
				bo.atmosphere
			)
		];
	}
}

/**
 * Reverse of {@link upgradeBodyMesh}: dispose the sphere mesh, atmosphere, and
 * eclipse shadow, reverting to a labelled halo. Non-probe types also lose their
 * trail; probes keep theirs (halo-only mode is "halo + trail, no mesh").
 */
export function downgradeBodyMesh(
	bo: BodyObjects,
	scene: Scene,
	clickables: Mesh[],
	meshToBody: Map<Mesh, PositionedBody>
): void {
	bo.focusUpgraded = false;
	// Dispose the 3D model first to release its textures + geometry before the
	// sphere teardown below.
	unloadBodyModel(bo);
	const mesh = bo.mesh;
	if (mesh) {
		// Material dispose below doesn't release textures, and a high-tier
		// DataTexture pins its full CPU-side buffer.
		if (bo.displacementMap) {
			bo.displacementMap.dispose();
			bo.displacementMap = null;
			bo.displacementTier = undefined;
			detachSelfShadow(bo.selfShadow);
			bo.selfShadow = null;
		}
		bo.terrainWindow = null;
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
		bo.sunTint = undefined;
		// Re-upgrade builds a fresh identity-scale mesh, so triaxial scale must
		// be reapplied; `bo.radiusScene` keeps its bumped value for that.
		bo.radiiApplied = false;
		bo.semiAxesScene = undefined;
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
