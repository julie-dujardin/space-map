import type { PerspectiveCamera, Points, ShaderMaterial, Vector3, WebGLRenderer } from 'three';
import { ObjectType } from '$lib/types/objects';
import { VISIBILITY } from '$lib/scene/context-manager.svelte';
import { BARYCENTER_PRIMARY } from '$lib/constants';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import {
	applyLabelDisplay,
	isScreenOccluded,
	cullOverlappingLabels,
	type ScreenOccluder
} from '../label/culling';
import { HALO_RADIUS_PX, type BodyObjects } from '../types';
import { moonVisFlags, bodyVisFlags } from './flags';
import { f64dist, type Vec3 } from '../animation/math';

/**
 * Per-frame visibility update for all bodies, point clouds, labels, and orbit lines.
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

	// Pre-pass: for each body with a label and a finite radius, compute the
	// visible-disc center on screen and offset `label.position` so the CSS2D
	// label renders at that center (not the projected body-center, which can
	// be tens of pixels off-disc for a close off-axis body — Earth seen from a
	// LEO sat, Saturn seen from one of its moons).
	//
	// Math: for a sphere at camera-frame position (Bx, By, Bz) with radius r,
	// the silhouette is a 3D circle whose projection to screen is an ellipse
	// whose center is at body_NDC · β where β = Bz²/(Bz²−r²). (Derived from
	// the tangent-cone conic — the body's geometric center projection is *not*
	// the ellipse center under perspective; it's shifted radially inward.)
	// To realise this with CSS2DRenderer, the label local position in camera
	// frame is ((β−1)·Bx, (β−1)·By, 0); rotated by camera.quaternion it
	// becomes the scene-frame offset stored on label.position.
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

	// Build screen-space occluder list: bodies whose sphere fills enough of
	// the screen to hide labels behind them. Disc radius uses the ellipse's
	// perpendicular axis (r·f / √(Bz²−r²)) — the smaller of the two for
	// off-axis bodies, so we don't over-occlude. The center is the projected
	// label position (already silhouette-corrected above).
	const screenOccluders: ScreenOccluder[] = [];
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
		screenOccluders.push({
			sx: (tmpV3.x * 0.5 + 0.5) * screenW,
			sy: (-tmpV3.y * 0.5 + 0.5) * screenH,
			r: screenR,
			id: bo.body.data.id,
			dist
		});
	}

	for (const bo of bodyObjects.values()) {
		const { body, group, orbitLine } = bo;
		const dist = bo.cachedDist;

		let showLabel: boolean;
		let isClose: boolean;
		const isFocused = body.data.id === focusedBodyId;

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
				if (orbitLine) orbitLine.visible = visible;
				showLabel = visible;
				isClose = false;
			} else {
				const vis = ctx.getPlanetVisibility(body, dist);
				const visible = vis !== VISIBILITY.HIDE && ctx.hasFullRendering(body);
				group.visible = visible;
				if (orbitLine) orbitLine.visible = visible;
				showLabel = visible;
				isClose = false;
			}
		} else {
			// Moons, planets, spacecraft, asteroids, comets, dwarf planets
			const isMoon = body.data.objectType === ObjectType.MOON;
			const vis = isMoon ? ctx.getMoonVisibility(body) : ctx.getPlanetVisibility(body, dist);
			const vf = isMoon
				? moonVisFlags(vis, hideCappedMoonLabels, isFocused)
				: bodyVisFlags(vis, ctx.hasFullRendering(body), isFocused);
			group.visible = vf.groupVisible;
			if (orbitLine) orbitLine.visible = vf.orbitVisible;
			showLabel = vf.showLabel;
			isClose = vf.isClose;
		}

		// Propagation was skipped this frame because jd is outside the chunk's
		// validity window — force the whole body hidden so it doesn't linger at
		// its last valid position.
		if (bo.outOfRange) {
			group.visible = false;
			if (orbitLine) orbitLine.visible = false;
			showLabel = false;
		}

		// Star extras: sub-pixel dot toggles with mesh size; stars always
		// keep their group visible and derive isClose from screen size
		// (they have no orbital semi-major axis, so the tier is always FULL).
		if (bo.starPoint) {
			const screenR = (bo.radiusScene / dist) * projScale;
			bo.starPoint.visible = screenR < 1;
			group.visible = true;
			isClose = screenR >= 1;
			showLabel = !isClose;
		}

		// Minor-promoted halos: ring stays (label.visible left alone so the DOM
		// element keeps rendering), but the trail draws only on focus. The name
		// span and halo scale are handled in cullOverlappingLabels.
		if (bo.isMinor && !isFocused && orbitLine) {
			orbitLine.visible = false;
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
	}

	for (const [zone, pts] of asteroidPoints) {
		pts.visible = ctx.isAsteroidGroupVisible(zone);
	}
	for (const [gid, pts] of spacecraftPoints) {
		pts.visible = ctx.isSpacecraftGroupVisible(gid);
	}
	for (const [parentId, pts] of moonPoints) {
		pts.visible = ctx.isMoonGroupVisible(parentId);
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

	// Update camera-relative offset uniforms for trail lines (prevents float32 precision flicker)
	// Also update alpha multiplier for hover/focus highlight
	for (const bo of bodyObjects.values()) {
		const line = bo.orbitLine;
		if (!line?.visible) continue;
		const mat = line.material as ShaderMaterial;
		// Orbit line vertices are written focus-relative (by refreshOrbitLineGeometry
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
