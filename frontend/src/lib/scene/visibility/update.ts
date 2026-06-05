import type { PerspectiveCamera, Points, ShaderMaterial, Vector3, WebGLRenderer } from 'three';
import { ObjectType } from '$lib/types/objects';
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
		o = { sx: 0, sy: 0, r: 0, id: '', dist: 0 };
		_occluderPool[idx] = o;
	}
	return o;
}

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
	tmpV3: Vector3
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
	// Silhouette-ellipse center under perspective = body_NDC · β where
	// β = Bz²/(Bz²−r²); local-frame offset is ((β−1)·Bx, (β−1)·By, 0).
	const fp = focusTruePos;
	const cameraInverse = camera.matrixWorldInverse;
	for (const bo of bodyObjects.values()) {
		bo.cachedDist = f64dist(camTrue, bo.body.position);
		const label = bo.label;
		if (!label) continue;
		const r = bo.radiusScene;
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
		if (camZ2 <= r2) {
			label.position.set(0, 0, 0);
			continue;
		}
		const beta1 = r2 / (camZ2 - r2); // β − 1
		tmpV3.set(beta1 * camX, beta1 * camY, 0).applyQuaternion(camera.quaternion);
		label.position.copy(tmpV3);
	}

	// Screen occluders: bodies large enough on-screen to hide labels behind them.
	// Uses the ellipse's minor axis radius (r·f / √(Bz²−r²)) to avoid over-occluding
	// off-axis bodies. Center = already-silhouette-corrected label position.
	const screenOccluders = _occluderPool;
	let occluderCount = 0;
	for (const bo of bodyObjects.values()) {
		const r = bo.radiusScene;
		if (!r) continue;
		const dist = bo.cachedDist;
		if (dist <= r) continue;
		const [bx, by, bz] = bo.body.position;
		tmpV3.set(bx - fp[0], by - fp[1], bz - fp[2]).applyMatrix4(cameraInverse);
		const camZ2 = tmpV3.z * tmpV3.z;
		if (camZ2 <= r * r) continue;
		const screenR = (r * projScale) / Math.sqrt(camZ2 - r * r);
		if (screenR < HALO_RADIUS_PX) continue;
		const lp = bo.label?.position;
		const ox = lp?.x ?? 0,
			oy = lp?.y ?? 0,
			oz = lp?.z ?? 0;
		tmpV3.set(bx - fp[0] + ox, by - fp[1] + oy, bz - fp[2] + oz);
		tmpV3.project(camera);
		if (tmpV3.z > 1) continue;
		const occ = ensureOccluder(occluderCount++);
		occ.sx = (tmpV3.x * 0.5 + 0.5) * screenW;
		occ.sy = (-tmpV3.y * 0.5 + 0.5) * screenH;
		occ.r = screenR;
		occ.id = bo.body.data.id;
		occ.dist = dist;
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
	for (const bo of bodyObjects.values()) {
		const { body, group, trail } = bo;
		const dist = bo.cachedDist;

		let showLabel: boolean;
		let isClose: boolean;
		const isFocused = body.data.id === focusedBodyId;
		const isSystemRoot = focusedSystemId !== null && body.data.id === focusedSystemId;

		if (bo.mesh === null) {
			// Halo-only bodies fall into two categories with different gates:
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

		applyLabelDisplay(bo, showLabel, isClose, dist, projScale, focusedBodyId);

		const nomScreenR = bo.radiusScene > 0 ? (bo.radiusScene / dist) * projScale : 0;
		updateNomenclatureVisibility(bo, isFocused, nomScreenR, camera, screenW, screenH);
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

	if (++cullFrameCounter >= 3) {
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
	if (focusedBodyId) {
		const focusedBo = bodyObjects.get(focusedBodyId);
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
