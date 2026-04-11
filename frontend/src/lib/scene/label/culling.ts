import { Vector3, type PerspectiveCamera } from 'three';
import { ObjectType } from '$lib/types/objects';
import { VISIBILITY, type ContextManager } from '$lib/scene/context-manager.svelte';
import {
	HIDE_LABEL_BODY_HALO_FACTOR,
	HALO_RADIUS_PX,
	typePriority,
	type BodyObjects
} from '../types';

// Reusable Vector3 — safe because all usage is synchronous/non-reentrant
const _tmpProj = new Vector3();

/**
 * Screen-space occluder: a body whose sphere is large enough on screen to
 * hide labels (and star coronas) that project behind it.
 */
export type ScreenOccluder = {
	sx: number;
	sy: number;
	r: number;
	id: string;
	dist: number;
};

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
 * Returns true when a screen point is inside any occluder disc that is closer
 * to the camera. Used for star corona/lensflare occlusion from the renderer.
 */
export function isScreenOccluded(
	sx: number,
	sy: number,
	dist: number,
	selfId: string,
	occluders: ScreenOccluder[]
): boolean {
	for (const occ of occluders) {
		if (occ.id === selfId) continue;
		if (occ.dist >= dist) continue;
		const dx = sx - occ.sx,
			dy = sy - occ.sy;
		if (dx * dx + dy * dy < occ.r * occ.r) return true;
	}
	return false;
}

type Candidate = {
	bodyId: string;
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

// Reusable arrays — cleared each frame, avoids per-frame allocation
const _candidates: Candidate[] = [];
const _accepted: { x: number; y: number }[] = [];

export function cullOverlappingLabels(
	bodyObjects: Map<string, BodyObjects>,
	screenWidth: number,
	screenHeight: number,
	camera: PerspectiveCamera,
	focusedBodyId: string | undefined,
	ctx: ContextManager,
	hoveredBodyIds: Set<string>,
	screenOccluders: ScreenOccluder[],
	focusTruePos: [number, number, number] = [0, 0, 0]
): void {
	// Estimated label bounding box in CSS pixels
	const LW = 90;
	const LH = 22;

	_candidates.length = 0;
	_accepted.length = 0;

	for (const bo of bodyObjects.values()) {
		const { body, label, labelHalo } = bo;
		if (!label?.visible) continue;
		// Focus-relative position for projection (matches camera's coordinate space)
		const [bx, by, bz] = body.position;
		_tmpProj.set(bx - focusTruePos[0], by - focusTruePos[1], bz - focusTruePos[2]);
		_tmpProj.project(camera);
		if (_tmpProj.z > 1) continue;
		const isFocused = body.data.id === focusedBodyId;
		const isHovered = hoveredBodyIds.has(body.data.id);
		_candidates.push({
			bodyId: body.data.id,
			body,
			label,
			labelHalo,
			isCapped:
				body.data.objectType === ObjectType.MOON
					? ctx.getMoonVisibility(body) === VISIBILITY.CAPPED
					: false,
			isFocused,
			isSelected: isFocused || isHovered,
			screenX: (_tmpProj.x * 0.5 + 0.5) * screenWidth,
			screenY: (-_tmpProj.y * 0.5 + 0.5) * screenHeight,
			dist: bo.cachedDist
		});
	}

	// Sort: selected first, then by type priority, then closer first
	_candidates.sort((a, b) => {
		if (a.isSelected !== b.isSelected) return a.isSelected ? -1 : 1;
		const pa = typePriority(a.body.data.objectType);
		const pb = typePriority(b.body.data.objectType);
		if (pa !== pb) return pa - pb;
		return a.dist - b.dist;
	});

	for (const {
		bodyId,
		label,
		labelHalo,
		isCapped,
		isFocused,
		isSelected,
		screenX,
		screenY,
		dist
	} of _candidates) {
		const nameSpan = labelHalo?.nextElementSibling as HTMLElement | null;
		if (isCapped && !isSelected) {
			dimLabel(labelHalo, nameSpan);
			continue;
		}
		// Check if behind a screen occluder (body large enough to hide labels behind it)
		if (!isSelected && isScreenOccluded(screenX, screenY, dist, bodyId, screenOccluders)) {
			label.visible = false;
			continue;
		}
		const overlaps = _accepted.some(
			({ x, y }) => Math.abs(screenX - x) < LW && Math.abs(screenY - y) < LH
		);
		if (!overlaps) {
			_accepted.push({ x: screenX, y: screenY });
			restoreLabel(labelHalo, nameSpan, hoveredBodyIds.has(bodyId), isFocused);
		} else {
			dimLabel(labelHalo, nameSpan);
		}
	}

	// Release references to avoid retaining body objects between frames
	_candidates.length = 0;
}
