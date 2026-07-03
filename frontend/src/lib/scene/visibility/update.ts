import { Quaternion, Vector3 } from 'three';
import type { PerspectiveCamera, Points, ShaderMaterial, WebGLRenderer } from 'three';
import { ObjectType, isMajorBody } from '$lib/types/objects';
import { sceneToKm } from '$lib/math/units';
import { setLabelNote } from '../label/factory';
import {
	ellipsoidCameraAxes,
	ellipsoidAnchorOffset,
	setSphereOccluder,
	setEllipsoidOccluder
} from './ellipsoid';
import { VISIBILITY } from './thresholds';
import { BARYCENTER_PRIMARY } from '$lib/constants';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import {
	applyLabelDisplay,
	isScreenOccluded,
	cullOverlappingLabels,
	refreshVisibleBodyLabelRects,
	type ScreenOccluder
} from '../label/culling';
import { HALO_RADIUS_PX, type BodyObjects } from '../types';
import { moonVisFlags, bodyVisFlags } from './flags';
import {
	updateNomenclatureVisibility,
	cullOverlappingNomenclatureLabels
} from '../objects/surface/nomenclature';
import { f64dist, type Vec3 } from '../animation/math';
import { modelUnitScene, type OccluderSphere } from '../objects/body/model';
import { parentIdFromSubkey } from '$lib/math/orbit/partition';
import {
	STAR_POINT_FLOOR_INTENSITY,
	STAR_POINT_HANDOFF_INTENSITY,
	STAR_POINT_SIZE_PX
} from '../objects/sun';

/**
 * Screen radius (px) at which the photosphere mesh hands off to the star
 * point: the mesh's projected disc and the point sprite cover the same area
 * here, so the two render contributions can be matched in HDR for a smooth
 * bloom transition. See `STAR_POINT_HANDOFF_INTENSITY` for the brightness
 * side of the handoff.
 */
const STAR_POINT_HANDOFF_R = STAR_POINT_SIZE_PX / 2;

// Pooled occluder array — reused across frames; trimmed to active prefix via
// `.length = active` so existing iter/`for-of` consumers keep working. Empty
// frames cost zero allocations (vs. `const x = []` + N pushes the old way).
const _occluderPool: ScreenOccluder[] = [];
function ensureOccluder(idx: number): ScreenOccluder {
	let o = _occluderPool[idx];
	if (!o) {
		o = {
			cx0: 0,
			cy0: 0,
			f: 0,
			gxx: 0,
			gxy: 0,
			gxz: 0,
			gyx: 0,
			gyy: 0,
			gyz: 0,
			gzx: 0,
			gzy: 0,
			gzz: 0,
			cpx: 0,
			cpy: 0,
			cpz: 0,
			K: 0,
			id: '',
			dist: 0
		};
		_occluderPool[idx] = o;
	}
	return o;
}

// Scratch for reading a mesh's world orientation when building ellipsoid occluders.
const _meshQuat = new Quaternion();
const _anchorOut = { ox: 0, oy: 0 };
// Scratch for the focused model's per-sphere occluder centers.
const _modelSphereCenter = new Vector3();

/**
 * Per-frame visibility update for all bodies, point clouds, labels, and trails.
 * Returns the updated cull frame counter and screen occluders (for shadow logic).
 */
export function updateBodyVisibility(
	bodyObjects: Map<string, BodyObjects>,
	camera: PerspectiveCamera,
	ctx: ContextManager,
	focusTruePos: Vec3,
	focusedBodyId: string | undefined,
	hideCappedMoonLabels: boolean,
	hoveredBodyIds: Set<string>,
	asteroidPoints: Map<string, Points>,
	spacecraftPoints: Map<string, Points>,
	moonPoints: Map<string, Points>,
	cullFrameCounter: number,
	renderer: WebGLRenderer,
	tmpV3: Vector3,
	forceCull: boolean
): number {
	const fovRad = (camera.fov * Math.PI) / 180;
	const screenW = renderer.domElement.clientWidth;
	const screenH = renderer.domElement.clientHeight;
	const projScale = screenH / (2 * Math.tan(fovRad / 2));

	// Camera true world position for Float64 distance calculations
	const camTrue: Vec3 = [
		focusTruePos[0] + camera.position.x,
		focusTruePos[1] + camera.position.y,
		focusTruePos[2] + camera.position.z
	];

	// Pre-pass: offset each body's label to its silhouette-disc center on
	// screen, not the projected body center (which is tens of pixels off-disc
	// for close off-axis bodies — LEO sat seeing Earth, moon seeing Saturn).
	// Sphere: silhouette-ellipse center under perspective = body_NDC · β where
	// β = Bz²/(Bz²−r²); local-frame offset is ((β−1)·Bx, (β−1)·By, 0). Oblate
	// bodies use the exact ellipsoid silhouette center (see ellipsoidAnchorOffset).
	const fp = focusTruePos;
	const cameraInverse = camera.matrixWorldInverse;
	for (const bo of bodyObjects.values()) {
		bo.cachedDist = f64dist(camTrue, bo.body.position);
		// Note pops in once close enough that a body would be expected: 100 m for
		// spacecraft (no model), 1 km for natural bodies (no measured size).
		if (bo.noPhysical) {
			setLabelNote(bo, sceneToKm(bo.cachedDist) < (bo.noPhysical === 'model' ? 0.1 : 1));
		}
		const label = bo.label;
		if (!label) continue;
		// No disc to anchor to — keep the label on-center.
		const r = bo.noPhysical ? 0 : bo.radiusScene;
		if (!r) {
			label.position.set(0, 0, 0);
			continue;
		}
		const [bx, by, bz] = bo.body.position;
		tmpV3.set(bx - fp[0], by - fp[1], bz - fp[2]).applyMatrix4(cameraInverse);
		const camX = tmpV3.x,
			camY = tmpV3.y,
			camZ = tmpV3.z;
		const camZ2 = camZ * camZ;
		const r2 = r * r;
		// Bail using the bounding-sphere limb: past it the silhouette is unbounded
		// and the body fills the screen (label hidden anyway).
		if (camZ2 <= r2) {
			label.position.set(0, 0, 0);
			continue;
		}
		// Sub-pixel bodies: silhouette center and body center differ by < screenR
		// px, so the offset is invisible — skip the per-body solve (a full conic
		// solve for ellipsoids).
		if ((r / bo.cachedDist) * projScale < 1) {
			label.position.set(0, 0, 0);
			continue;
		}
		if (bo.semiAxesScene && bo.mesh) {
			const ax = ellipsoidCameraAxes(
				bo.mesh.getWorldQuaternion(_meshQuat),
				cameraInverse,
				bo.semiAxesScene
			);
			ellipsoidAnchorOffset(camX, camY, camZ, ax, projScale, _anchorOut);
			tmpV3.set(_anchorOut.ox, _anchorOut.oy, 0).applyQuaternion(camera.quaternion);
		} else {
			const beta1 = r2 / (camZ2 - r2); // β − 1
			tmpV3.set(beta1 * camX, beta1 * camY, 0).applyQuaternion(camera.quaternion);
		}
		label.position.copy(tmpV3);
	}

	// Screen occluders: bodies large enough on-screen to hide labels behind them,
	// stored as tangent cones (see ScreenOccluder) so the silhouette test stays
	// valid even when the limb crosses the camera plane (Bz² ≤ r²).
	const screenOccluders = _occluderPool;
	const halfW = screenW * 0.5,
		halfH = screenH * 0.5;
	let occluderCount = 0;
	for (const bo of bodyObjects.values()) {
		// No disc → can't occlude other labels.
		const r = bo.noPhysical ? 0 : bo.radiusScene;
		if (!r) continue;
		const dist = bo.cachedDist;
		if (dist <= r) continue; // camera inside the bounding sphere → no occlusion
		const [bx, by, bz] = bo.body.position;
		tmpV3.set(bx - fp[0], by - fp[1], bz - fp[2]).applyMatrix4(cameraInverse);
		const camX = tmpV3.x,
			camY = tmpV3.y,
			camZ = tmpV3.z;
		if (camZ >= 0) continue; // body center behind the camera
		const bz2 = camZ * camZ;
		// Gate on the bounding-sphere tangential screen radius ≥ halo size (over-
		// includes oblate bodies, which the exact cone test below then refines);
		// bz² ≤ r² means the body engulfs the view, so it's always an occluder.
		const gateOk = bz2 <= r * r || (r * projScale) / Math.sqrt(bz2 - r * r) >= HALO_RADIUS_PX;
		if (!gateOk) continue;
		const modelSpheres = bo.model?.userData.occluderSpheres as OccluderSphere[] | undefined;
		if (bo.model && modelSpheres?.length) {
			// Focused body rendered as an overlay model: occlude with the sphere
			// chain fitted at load — a single bounding ellipsoid lets labels peek
			// through bent/elongated shapes. Centers live in the model's rotation
			// frame; the model sits at the overlay root, so its local quaternion
			// is its world attitude and `model.position` is the recentring shift.
			const s = modelUnitScene(bo);
			const mp = bo.model.position;
			for (const sphere of modelSpheres) {
				const rSphere = sphere.r * s;
				_modelSphereCenter
					.copy(sphere.center)
					.applyQuaternion(bo.model.quaternion)
					.add(mp)
					.multiplyScalar(s);
				tmpV3
					.set(
						bx - fp[0] + _modelSphereCenter.x,
						by - fp[1] + _modelSphereCenter.y,
						bz - fp[2] + _modelSphereCenter.z
					)
					.applyMatrix4(cameraInverse);
				if (tmpV3.z >= 0 || tmpV3.lengthSq() <= rSphere * rSphere) continue;
				const so = ensureOccluder(occluderCount++);
				setSphereOccluder(
					so,
					tmpV3.x,
					tmpV3.y,
					tmpV3.z,
					rSphere,
					projScale,
					halfW,
					halfH,
					bo.body.data.id,
					dist
				);
			}
		} else if (bo.semiAxesScene && bo.mesh) {
			const occ = ensureOccluder(occluderCount++);
			const ax = ellipsoidCameraAxes(
				bo.mesh.getWorldQuaternion(_meshQuat),
				cameraInverse,
				bo.semiAxesScene
			);
			setEllipsoidOccluder(
				occ,
				camX,
				camY,
				camZ,
				ax,
				projScale,
				halfW,
				halfH,
				bo.body.data.id,
				dist
			);
		} else {
			const occ = ensureOccluder(occluderCount++);
			setSphereOccluder(occ, camX, camY, camZ, r, projScale, halfW, halfH, bo.body.data.id, dist);
		}
	}
	// Trim the pool view to the active prefix so .length-based iteration is
	// correct in downstream consumers (cullOverlappingLabels, this function's
	// later isScreenOccluded call). Slots past occluderCount keep their last
	// values but are invisible to length-bounded iteration; no per-frame alloc.
	screenOccluders.length = occluderCount;

	// When the focused body is an asteroid moon, the parent asteroid becomes the
	// focused-system root. Treating it as "focused" for visibility keeps its trail
	// from being suppressed by the CLOSE-and-not-focused gate in bodyVisFlags.
	const focusedSystemId = ctx.visibility.focusedSystemId;

	// Set when a label flips hidden→visible this frame: forces the cull below so
	// freshly-shown labels render already-culled instead of flashing maximized
	// for the 1–2 frames until the throttled (every-3rd-frame) cull would run.
	let newlyShownLabel = false;

	// Landed probe defers to its landing body for surface-label focus.
	let nomFocusedBodyId = focusedBodyId;
	if (focusedBodyId) {
		const focusedBo = bodyObjects.get(focusedBodyId);
		if (focusedBo?.isLanded) nomFocusedBodyId = focusedBo.body.data.parentId;
	}
	for (const bo of bodyObjects.values()) {
		const { body, group, trail } = bo;
		const dist = bo.cachedDist;

		let showLabel: boolean;
		let isClose: boolean;
		const isFocused = body.data.id === focusedBodyId;
		const isSystemRoot = focusedSystemId !== null && body.data.id === focusedSystemId;

		// Major bodies (planets/moons/dwarfs/stars) always take the mesh path's
		// type-aware gates even when sizeless and meshless — else they'd skip the
		// moon-label cap and show every halo unbounded.
		if (bo.mesh === null && !isMajorBody(body.data.objectType)) {
			// Halo-only minor bodies fall into two categories with different gates:
			// - Barycenters / Lagrange points: navigational aids, always visible
			//   once built (with a barycenter-primary overlap check so SSB/Sun
			//   and Pluto-BC/Pluto don't stack).
			// - Auto-promoted asteroids/comets/probes (label+halo entries with
			//   no mesh): apply the same distance-ratio threshold + active-system
			//   gate as the mesh path, so they fade out when zooming into a
			//   planet system (matching the point-cloud behavior they replace).
			const ot = body.data.objectType;
			if (ot === ObjectType.BARYCENTER || ot === ObjectType.LAGRANGE_POINT) {
				let visible = true;
				const primaryId = !isFocused ? BARYCENTER_PRIMARY.get(body.data.id) : undefined;
				if (primaryId) {
					const primaryBo = bodyObjects.get(primaryId);
					if (primaryBo) {
						const sepWorld = f64dist(body.position, primaryBo.body.position);
						const camToPrimary = f64dist(camTrue, primaryBo.body.position);
						const pxSep = (sepWorld / camToPrimary) * projScale;
						if (pxSep < HALO_RADIUS_PX) visible = false;
					}
				}
				group.visible = visible;
				if (trail) trail.visible = visible;
				showLabel = visible;
				isClose = false;
			} else {
				const vis = ctx.visibility.getPlanetVisibility(body, dist);
				const visible = vis !== VISIBILITY.HIDE && ctx.visibility.hasFullRendering(body);
				group.visible = visible;
				if (trail) trail.visible = visible;
				showLabel = visible;
				isClose = false;
			}
		} else {
			// Moons, planets, spacecraft, asteroids, comets, dwarf planets
			const isMoon = body.data.objectType === ObjectType.MOON;
			const vis = isMoon
				? ctx.visibility.getMoonVisibility(body)
				: ctx.visibility.getPlanetVisibility(body, dist);
			const vf = isMoon
				? moonVisFlags(vis, hideCappedMoonLabels, isFocused)
				: bodyVisFlags(vis, ctx.visibility.hasFullRendering(body), isFocused || isSystemRoot);
			group.visible = vf.groupVisible;
			if (trail) trail.visible = vf.orbitVisible;
			showLabel = vf.showLabel;
			isClose = vf.isClose;
		}

		// Propagation was skipped this frame because jd is outside the chunk's
		// validity window — force the whole body hidden so it doesn't linger at
		// its last valid position.
		if (bo.outOfRange) {
			group.visible = false;
			if (trail) trail.visible = false;
			showLabel = false;
		}

		// Star extras: the point sprite takes over once the mesh disc has
		// shrunk to the point's own on-screen area (`screenR < SIZE/2`), so
		// the two cover the same number of pixels at the handoff and the
		// alpha-blended overlap can be matched in HDR. Beyond the handoff
		// the point's `uIntensity` falls as the squared ratio of the current
		// to handoff screen radius — equivalent to the physical 1/d²
		// apparent-flux law since `screenR ∝ 1/d`. The floor keeps the dot
		// visible at LDR (no bloom) once the apparent flux drops below the
		// bloom threshold — roughly the look of the Sun from Pluto's orbit.
		if (bo.starPoint) {
			const screenR = (bo.radiusScene / dist) * projScale;
			const subPixel = screenR < STAR_POINT_HANDOFF_R;
			bo.starPoint.visible = subPixel;
			if (subPixel) {
				const material = bo.starPoint.material as ShaderMaterial;
				const t = screenR / STAR_POINT_HANDOFF_R;
				const intensity = Math.max(
					STAR_POINT_HANDOFF_INTENSITY * t * t,
					STAR_POINT_FLOOR_INTENSITY
				);
				material.uniforms.uIntensity.value = intensity;
			}
			group.visible = true;
			isClose = !subPixel;
			showLabel = !isClose;
		}

		// Minor-promoted halos: ring stays (label.visible left alone so the DOM
		// element keeps rendering), but the trail draws only on focus. The name
		// span and halo scale are handled in cullOverlappingLabels.
		if (bo.isMinor && !isFocused && trail) {
			trail.visible = false;
		}

		// Detach labels from hidden groups so CSS2DRenderer's recursive
		// renderObject() doesn't visit them and write display:'none' every frame.
		// Re-attach when the group becomes visible — CSS2DRenderer re-appends
		// the DOM element automatically on next render.
		// Required for good safari performance
		const { label } = bo;
		if (!group.visible && label && label.parent === group) {
			group.remove(label);
			label.element.remove();
		} else if (group.visible && label && label.parent !== group) {
			group.add(label);
		}

		if (applyLabelDisplay(bo, showLabel, isClose, dist, projScale, focusedBodyId)) {
			newlyShownLabel = true;
		}

		const nomScreenR = bo.radiusScene > 0 ? (bo.radiusScene / dist) * projScale : 0;
		const isNomFocused = body.data.id === nomFocusedBodyId;
		updateNomenclatureVisibility(bo, isNomFocused, nomScreenR, camera, screenW, screenH);
	}

	// Keys are subgroup keys (`${zone}#${i}`) from PointCloudSystem's hash-split.
	for (const [key, pts] of asteroidPoints) {
		pts.visible = ctx.visibility.isAsteroidGroupVisible(parentIdFromSubkey(key));
	}
	for (const [key, pts] of spacecraftPoints) {
		pts.visible = ctx.visibility.isSpacecraftGroupVisible(parentIdFromSubkey(key));
	}
	for (const [parentId, pts] of moonPoints) {
		pts.visible = ctx.visibility.isMoonGroupVisible(parentId);
	}

	// Screen-space label occlusion runs every frame (cheap: typically 0-2 occluders).
	// Overlap culling is throttled to every 3rd frame.
	if (screenOccluders.length > 0) {
		for (const bo of bodyObjects.values()) {
			if (!bo.label?.visible) continue;
			const [bx, by, bz] = bo.body.position;
			const lp = bo.label.position;
			tmpV3.set(bx - fp[0] + lp.x, by - fp[1] + lp.y, bz - fp[2] + lp.z);
			tmpV3.project(camera);
			if (tmpV3.z > 1) continue;
			if (
				isScreenOccluded(
					(tmpV3.x * 0.5 + 0.5) * screenW,
					(-tmpV3.y * 0.5 + 0.5) * screenH,
					bo.cachedDist,
					bo.body.data.id,
					screenOccluders
				)
			) {
				bo.label.visible = false;
			}
		}
	}

	// While the camera moves, label screen positions change every frame; the
	// throttled (every-3rd-frame) cull then judges overlaps against 1–2-frame-stale
	// positions and lets overlapping labels both stay maximized until motion stops.
	// Caller forces every-frame culling during camera motion; throttle when idle.
	if (forceCull || newlyShownLabel || ++cullFrameCounter >= 3) {
		cullFrameCounter = 0;
		cullOverlappingLabels(
			bodyObjects,
			screenW,
			screenH,
			camera,
			focusedBodyId,
			ctx,
			hoveredBodyIds,
			screenOccluders,
			focusTruePos
		);
	}

	// Re-project every visible+maximized body label every frame so the
	// nomenclature cull below sees fresh body rects, not the 0–2-frame-stale
	// snapshot from the throttled body cull above. Without this, feature
	// labels flicker briefly at the transition as a body label slides over.
	refreshVisibleBodyLabelRects(bodyObjects, screenW, screenH, camera, focusTruePos);

	// Feature-label collision cull runs every frame for the focused body only
	// (small N — visible labels per body, after size band, typically < 200).
	// Running every frame keeps it in sync with the per-frame size-band pass,
	// so labels that swap in/out of visibility don't flicker against a stale
	// throttled cull result.
	if (nomFocusedBodyId) {
		const focusedBo = bodyObjects.get(nomFocusedBodyId);
		if (focusedBo) cullOverlappingNomenclatureLabels(focusedBo);
	}

	// Update camera-relative offset uniforms for trail lines (prevents float32 precision flicker)
	// Also update alpha multiplier for hover/focus highlight
	for (const bo of bodyObjects.values()) {
		const line = bo.trail;
		if (!line?.visible) continue;
		const mat = line.material as ShaderMaterial;
		// Trail vertices are written focus-relative (by refreshTrail
		// every frame), so offset is simply −cam — tiny, keeping (vertex + offset)
		// precise in Float32 even for meter-scale viewing of distant bodies.
		mat.uniforms.uCenterOffset.value.set(
			-camera.position.x,
			-camera.position.y,
			-camera.position.z
		);
		const isFocused = bo.body.data.id === focusedBodyId;
		const isHovered = hoveredBodyIds.has(bo.body.data.id);
		mat.uniforms.uAlphaMultiplier.value = isHovered ? 2 : isFocused ? 1.75 : 1.0;
		mat.uniforms.uAlphaMin.value = isFocused ? 0.15 : 0.0;
		mat.uniforms.uShowFull.value = isFocused ? 1.0 : 0.0;
	}

	return cullFrameCounter;
}
