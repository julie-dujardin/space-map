import { Vector3, type PerspectiveCamera } from 'three';
import { ObjectType } from '$lib/types/objects';
import { VISIBILITY, type ContextManager } from '$lib/scene/context-manager.svelte';
import {
	HIDE_LABEL_BODY_HALO_FACTOR,
	HALO_RADIUS_PX,
	typePriority,
	type BodyObjects
} from '../types';

export function dimLabel(labelHalo: HTMLElement | null, nameSpan: HTMLElement | null): void {
	if (labelHalo) labelHalo.style.transform = 'scale(0.3)';
	if (nameSpan) {
		nameSpan.style.display = 'none';
		nameSpan.style.fontSize = '';
	}
}

export function restoreLabel(
	labelHalo: HTMLElement | null,
	nameSpan: HTMLElement | null,
	isHovered: boolean,
	isFocused: boolean
): void {
	if (labelHalo) {
		if (!isHovered) labelHalo.style.transform = '';
		labelHalo.style.border = labelHalo.dataset.origBorder ?? '';
	}
	if (nameSpan) {
		nameSpan.style.display = '';
		nameSpan.style.fontSize = isFocused ? '18px' : '';
	}
}

/**
 * Applies label visibility for a body, handling the close-in case where the
 * rendered sphere is large enough to replace the halo indicator.
 */
export function applyLabelDisplay(
	bo: BodyObjects,
	show: boolean,
	isClose: boolean,
	distToBody: number,
	projScale: number,
	focusedBodyId: string | undefined
): void {
	const { label, labelHalo, radiusScene } = bo;
	if (!label) return;

	let hideHaloRing = false;
	let screenR = 0;

	if (!show && isClose) {
		screenR = (radiusScene / distToBody) * projScale;
		// For bodies that entered CLOSE state because the camera is near their parent
		// (e.g. outer moons when zoomed into Saturn), screenR is near-zero even though
		// the body is physically far. Skip the close logic unless we're actually zoomed
		// into this specific body (isFocused) or it's large enough on screen (screenR >= 1).
		const isFocused = bo.body.data.id === focusedBodyId;
		if (isFocused || screenR >= 1) {
			show = screenR < HALO_RADIUS_PX * HIDE_LABEL_BODY_HALO_FACTOR;
			hideHaloRing = screenR >= HALO_RADIUS_PX;
			if (bo.orbitLine) bo.orbitLine.visible = !hideHaloRing;
		}
	}

	label.visible = show;
	if (labelHalo) labelHalo.style.visibility = hideHaloRing ? 'hidden' : '';
	label.center.x = hideHaloRing ? 1 - screenR / 32 : 0.5;
}

/**
 * Returns true if the point (bx,by,bz) at distance bodyDist from the camera
 * lies within the angular cone of any planet sphere (i.e. is occluded by it).
 * selfId is excluded so a planet doesn't occlude its own label.
 */
export function isOccludedByPlanet(
	bx: number,
	by: number,
	bz: number,
	bodyDist: number,
	selfId: string,
	camPos: Vector3,
	bodyObjects: Map<string, BodyObjects>
): boolean {
	const tmpDir = new Vector3();
	const tmpPlanet = new Vector3();
	for (const bo of bodyObjects.values()) {
		if (bo.body.data.objectType !== ObjectType.PLANET) continue;
		if (bo.body.data.id === selfId) continue;
		tmpPlanet.set(...bo.body.position);
		const planetDist = camPos.distanceTo(tmpPlanet);
		if (planetDist >= bodyDist) continue; // planet is behind the body
		// Direction camera → body
		tmpDir.set(bx, by, bz).sub(camPos).normalize();
		// Direction camera → planet centre
		tmpPlanet.sub(camPos).normalize();
		const cosAngle = tmpDir.dot(tmpPlanet);
		if (cosAngle <= 0) continue;
		const sinOcclude = bo.radiusScene / planetDist;
		if (sinOcclude >= 1) continue;
		if (cosAngle >= Math.sqrt(1 - sinOcclude * sinOcclude)) return true;
	}
	return false;
}

export function cullOverlappingLabels(
	bodyObjects: Map<string, BodyObjects>,
	screenWidth: number,
	screenHeight: number,
	camera: PerspectiveCamera,
	focusedBodyId: string | undefined,
	ctx: ContextManager,
	focusTruePos: [number, number, number] = [0, 0, 0]
): void {
	// Estimated label bounding box in CSS pixels
	const LW = 90;
	const LH = 22;

	type Candidate = {
		body: BodyObjects['body'];
		label: NonNullable<BodyObjects['label']>;
		labelHalo: HTMLElement | null;
		isCapped: boolean;
		isFocused: boolean;
		isSelected: boolean;
		screenX: number;
		screenY: number;
		dist: number;
	};

	// Camera true world position (Float64)
	const camWx = focusTruePos[0] + camera.position.x;
	const camWy = focusTruePos[1] + camera.position.y;
	const camWz = focusTruePos[2] + camera.position.z;

	const tmpV3 = new Vector3();
	const candidates: Candidate[] = [];

	for (const { body, label, labelHalo } of bodyObjects.values()) {
		if (!label?.visible) continue;
		// Focus-relative position for projection (matches camera's coordinate space)
		const [bx, by, bz] = body.position;
		tmpV3.set(bx - focusTruePos[0], by - focusTruePos[1], bz - focusTruePos[2]);
		// Distance in Float64 from world positions
		const dx = bx - camWx,
			dy = by - camWy,
			dz = bz - camWz;
		const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
		tmpV3.project(camera);
		if (tmpV3.z > 1) continue;
		const isFocused = body.data.id === focusedBodyId;
		const isHovered = label.element.matches(':hover');
		candidates.push({
			body,
			label,
			labelHalo,
			isCapped:
				body.data.objectType === ObjectType.MOON
					? ctx.getMoonVisibility(body) === VISIBILITY.CAPPED
					: false,
			isFocused,
			isSelected: isFocused || isHovered,
			screenX: (tmpV3.x * 0.5 + 0.5) * screenWidth,
			screenY: (-tmpV3.y * 0.5 + 0.5) * screenHeight,
			dist
		});
	}

	// Sort: selected first, then by type priority, then closer first
	candidates.sort((a, b) => {
		if (a.isSelected !== b.isSelected) return a.isSelected ? -1 : 1;
		const pa = typePriority(a.body.data.objectType);
		const pb = typePriority(b.body.data.objectType);
		if (pa !== pb) return pa - pb;
		return a.dist - b.dist;
	});

	const accepted: { x: number; y: number }[] = [];
	for (const {
		label,
		labelHalo,
		isCapped,
		isFocused,
		isSelected,
		screenX,
		screenY
	} of candidates) {
		const nameSpan = labelHalo?.nextElementSibling as HTMLElement | null;
		if (isCapped && !isSelected) {
			dimLabel(labelHalo, nameSpan);
			continue;
		}
		const overlaps = accepted.some(
			({ x, y }) => Math.abs(screenX - x) < LW && Math.abs(screenY - y) < LH
		);
		if (!overlaps) {
			accepted.push({ x: screenX, y: screenY });
			restoreLabel(labelHalo, nameSpan, label.element.matches(':hover'), isFocused);
		} else {
			dimLabel(labelHalo, nameSpan);
		}
	}
}
