import type { PerspectiveCamera, Points, ShaderMaterial, Vector3, WebGLRenderer } from 'three';
import { ObjectType } from '$lib/types/objects';
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

	// Build screen-space occluder list: bodies whose sphere fills enough of
	// the screen to hide labels behind them (only when zoomed in close).
	const fp = focusTruePos;
	const screenOccluders: ScreenOccluder[] = [];
	for (const bo of bodyObjects.values()) {
		if (!bo.radiusScene) continue;
		const dist = f64dist(camTrue, bo.body.position);
		const screenR = (bo.radiusScene / dist) * projScale;
		if (screenR < HALO_RADIUS_PX) continue;
		const [bx, by, bz] = bo.body.position;
		tmpV3.set(bx - fp[0], by - fp[1], bz - fp[2]);
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
		const dist = f64dist(camTrue, body.position);
		bo.cachedDist = dist;

		let showLabel: boolean;
		let isClose: boolean;
		const isFocused = body.data.id === focusedBodyId;

		if (
			body.data.objectType === ObjectType.BARYCENTER ||
			body.data.objectType === ObjectType.LAGRANGE_POINT
		) {
			// Virtual bodies promoted via URL navigation: always visible once built
			group.visible = true;
			if (orbitLine) orbitLine.visible = true;
			showLabel = true;
			isClose = false;
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
			tmpV3.set(bx - fp[0], by - fp[1], bz - fp[2]);
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
