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

export function dimLabel(
	labelHalo: HTMLElement | null,
	nameSpan: HTMLElement | null,
	clickable: boolean,
	scale = 0.3
): void {
	if (labelHalo) {
		labelHalo.style.transform = `scale(${scale})`;
		// Without this, hovering a dimmed halo's 32×32 root re-maximizes it and
		// adds the body to hoveredBodyIds, stealing focus from whatever's behind.
		if (labelHalo.parentElement) {
			labelHalo.parentElement.style.pointerEvents = clickable ? '' : 'none';
		}
	}
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
		// A label unclickable on frame N must regain clicks when it wins frame N+1.
		if (labelHalo.parentElement) labelHalo.parentElement.style.pointerEvents = '';
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

	const screenR = radiusScene > 0 ? (radiusScene / distToBody) * projScale : 0;
	const isFocused = bo.body.data.id === focusedBodyId;
	// Hide the halo ring (and its accompanying trail) whenever the rendered
	// sphere is at least the halo's size — the sphere itself substitutes for
	// both indicators. Applies to any body type regardless of visibility tier.
	const hideHaloRing = screenR >= HALO_RADIUS_PX;

	if (!show && isClose) {
		// CLOSE tier but label was suppressed (e.g. outer moons when zoomed into
		// their parent system): re-show the label until the sphere fills most
		// of the screen. Skip unless we're actually zoomed into this body or
		// it's ≥1px onscreen — CLOSE can fire on distant bodies too.
		if (isFocused || screenR >= 1) {
			show = screenR < HALO_RADIUS_PX * HIDE_LABEL_BODY_HALO_FACTOR;
		}
	}
	if (bo.orbitLine && hideHaloRing) bo.orbitLine.visible = false;

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
	isMinor: boolean;
	isFocused: boolean;
	isSelected: boolean;
	screenX: number;
	screenY: number;
	labelLeft: number;
	labelRight: number;
	dist: number;
};

// Reusable arrays — cleared each frame, avoids per-frame allocation
const _candidates: Candidate[] = [];
const _accepted: { left: number; right: number; y: number }[] = [];

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
	const LH = 22;

	_candidates.length = 0;
	_accepted.length = 0;

	for (const bo of bodyObjects.values()) {
		const { body, label, labelHalo } = bo;
		if (!label?.visible) continue;
		// Lazy-measure label text width (element must be in DOM; cached forever)
		if (bo.labelTextWidth === undefined && labelHalo) {
			const span = labelHalo.nextElementSibling as HTMLElement | null;
			if (span) bo.labelTextWidth = span.offsetWidth;
		}
		// Focus-relative position for projection (matches camera's coordinate space).
		// label.position carries the silhouette offset (set in updateBodyVisibility)
		// so this projects to where the label actually renders on screen.
		const [bx, by, bz] = body.position;
		const lp = label.position;
		_tmpProj.set(
			bx - focusTruePos[0] + lp.x,
			by - focusTruePos[1] + lp.y,
			bz - focusTruePos[2] + lp.z
		);
		_tmpProj.project(camera);
		if (_tmpProj.z > 1) continue;
		const isFocused = body.data.id === focusedBodyId;
		const isHovered = hoveredBodyIds.has(body.data.id);
		const screenX = (_tmpProj.x * 0.5 + 0.5) * screenWidth;
		const screenY = (-_tmpProj.y * 0.5 + 0.5) * screenHeight;
		// Compute actual screen AABB accounting for center.x offset
		const rootLeft = screenX - label.center.x * 32;
		const textWidth = bo.labelTextWidth ?? 50;
		_candidates.push({
			bodyId: body.data.id,
			body,
			label,
			labelHalo,
			isCapped:
				body.data.objectType === ObjectType.MOON
					? ctx.getMoonVisibility(body) === VISIBILITY.CAPPED
					: false,
			isMinor: bo.isMinor,
			isFocused,
			isSelected: isFocused || isHovered,
			screenX,
			screenY,
			labelLeft: rootLeft,
			labelRight: rootLeft + 40 + textWidth,
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
		isMinor,
		isFocused,
		isSelected,
		screenX,
		screenY,
		labelLeft,
		labelRight,
		dist
	} of _candidates) {
		const nameSpan = labelHalo?.nextElementSibling as HTMLElement | null;
		// Minor-promoted: collapse to scale 0.3 (same as occluded) and hide the
		// name text. On hover/focus the candidate is "selected" and falls through
		// to the normal restoreLabel path so the halo grows back and the name
		// appears. `dimLabel` already produces the exact desired visual.
		if (isMinor && !isSelected) {
			dimLabel(labelHalo, nameSpan, true, 0.5);
			continue;
		}
		if (isCapped && !isSelected) {
			dimLabel(labelHalo, nameSpan, true);
			continue;
		}
		// Check if behind a screen occluder (body large enough to hide labels behind it)
		if (!isSelected && isScreenOccluded(screenX, screenY, dist, bodyId, screenOccluders)) {
			label.visible = false;
			continue;
		}
		const overlaps = _accepted.some(
			(a) => labelLeft < a.right && labelRight > a.left && Math.abs(screenY - a.y) < LH
		);
		if (!overlaps) {
			_accepted.push({ left: labelLeft, right: labelRight, y: screenY });
			restoreLabel(labelHalo, nameSpan, hoveredBodyIds.has(bodyId), isFocused);
		} else {
			dimLabel(labelHalo, nameSpan, false);
		}
	}

	// Release references to avoid retaining body objects between frames
	_candidates.length = 0;
}
