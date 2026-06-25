import { Vector3, type PerspectiveCamera } from 'three';
import { ObjectType } from '$lib/types/objects';
import { VISIBILITY } from '$lib/scene/visibility/thresholds';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import {
	HIDE_LABEL_BODY_HALO_FACTOR,
	HALO_RADIUS_PX,
	typePriority,
	type BodyObjects
} from '../types';

// Reusable Vector3 — safe because all usage is synchronous/non-reentrant
const _tmpProj = new Vector3();

/** Body-label vertical extent in px (text height + line-height + shadow).
 *  Used as the `h` field of every body-label accepted rect. */
const LH = 22;

/**
 * A body large enough on screen to hide labels behind it. The occluding region
 * is the body's tangent cone — the exact silhouette in every regime, including
 * when the limb crosses the camera plane (which the old screen-ellipse model
 * couldn't represent) and when the body is an oblate ellipsoid. The test runs in
 * the space where the body is a unit sphere: the scaled principal axes gᵢ = eᵢ/aᵢ
 * map a label's camera-space view ray d there (sphere = identity·1/r), and c' =
 * (c·eᵢ/aᵢ) is the normalized center with K = |c'|² − 1. isScreenOccluded
 * rebuilds d from the label's screen point (no per-call projection).
 */
export type ScreenOccluder = {
	cx0: number;
	cy0: number;
	f: number;
	gxx: number;
	gxy: number;
	gxz: number;
	gyx: number;
	gyy: number;
	gyz: number;
	gzx: number;
	gzy: number;
	gzz: number;
	cpx: number;
	cpy: number;
	cpz: number;
	K: number;
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
 * Returns true if the label transitioned hidden→visible this call, so the
 * caller can force a cull this frame (otherwise it renders un-culled — all
 * labels maximized — until the throttled cull catches up, a 1–2 frame flash).
 */
export function applyLabelDisplay(
	bo: BodyObjects,
	show: boolean,
	isClose: boolean,
	distToBody: number,
	projScale: number,
	focusedBodyId: string | undefined
): boolean {
	const { label, labelHalo, radiusScene } = bo;
	if (!label) return false;
	const wasVisible = label.visible;

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
	if (bo.trail && hideHaloRing) bo.trail.visible = false;

	label.visible = show;
	if (labelHalo) labelHalo.style.visibility = hideHaloRing ? 'hidden' : '';
	// Loader DOM node only exists while a model is loading (managed by
	// `setHaloLoading`). Show it exactly when the halo would be hidden by
	// the close-zoom rule — it sits at the viewport centre.
	if (bo.loadingEl) bo.loadingEl.style.display = hideHaloRing ? '' : 'none';
	label.center.x = hideHaloRing ? 1 - screenR / 32 : 0.5;
	return show && !wasVisible;
}

/** True when a screen point falls inside a closer occluder's silhouette cone. */
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
		// Map the label's camera-space view ray d = (u, v, −f) into the space where
		// the body is a unit sphere (d' = (d·gx, d·gy, d·gz)), then run the cone test
		// (d'·c')² > K·|d'|² with the ray pointing toward the body (d'·c' > 0).
		const u = sx - occ.cx0;
		const v = occ.cy0 - sy;
		const w = -occ.f;
		const p = u * occ.gxx + v * occ.gxy + w * occ.gxz;
		const q = u * occ.gyx + v * occ.gyy + w * occ.gyz;
		const s = u * occ.gzx + v * occ.gzy + w * occ.gzz;
		const root = p * occ.cpx + q * occ.cpy + s * occ.cpz;
		if (root <= 0) continue; // ray points to the far side of the body
		if (root * root > occ.K * (p * p + q * q + s * s)) return true;
	}
	return false;
}

type Candidate = {
	bodyId: string;
	bo: BodyObjects | null;
	body: BodyObjects['body'] | null;
	label: NonNullable<BodyObjects['label']> | null;
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

/** A label whose rect has won its slot in the cull pass. `h` is the label's
 *  vertical extent in px (body labels and nomenclature labels have different
 *  text heights — the overlap check averages the two to test box overlap). */
export type AcceptedRect = { left: number; right: number; y: number; h: number };

// Pool of Candidate / Accepted slots that grows on demand and never shrinks.
// Per-frame work mutates slots in place rather than allocating fresh objects —
// at ~150 candidates per cull (every 3rd frame) the alloc churn is the largest
// per-frame GC source in this hot path (≈4× faster than push-fresh in
// microbenchmarks). `_candidatesActive` tracks how many slots are populated.
const _candidates: Candidate[] = [];
let _candidatesActive = 0;
const _accepted: AcceptedRect[] = [];
let _acceptedActive = 0;

/** Read-only view of the body-label accepted rects from the latest cull. The
 *  nomenclature cull seeds itself with these so feature labels lose to any
 *  body label. `count` is a getter — the underlying pool is mutated in place. */
export const acceptedBodyLabelRects = {
	rects: _accepted as readonly AcceptedRect[],
	get count(): number {
		return _acceptedActive;
	}
};

function ensureCandidate(idx: number): Candidate {
	let c = _candidates[idx];
	if (!c) {
		c = {
			bodyId: '',
			bo: null,
			body: null,
			label: null,
			labelHalo: null,
			isCapped: false,
			isMinor: false,
			isFocused: false,
			isSelected: false,
			screenX: 0,
			screenY: 0,
			labelLeft: 0,
			labelRight: 0,
			dist: 0
		};
		_candidates[idx] = c;
	}
	return c;
}

function ensureAccepted(idx: number): AcceptedRect {
	let a = _accepted[idx];
	if (!a) {
		a = { left: 0, right: 0, y: 0, h: 0 };
		_accepted[idx] = a;
	}
	return a;
}

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
	_candidatesActive = 0;
	_acceptedActive = 0;

	for (const bo of bodyObjects.values()) {
		const { body, label, labelHalo } = bo;
		if (!label?.visible) continue;
		// Lazy-measure label text width, caching the first positive measurement.
		// A hidden name span (display:none from a prior dim) reports offsetWidth 0;
		// caching that would peg the label's overlap rect to halo-width forever, so
		// it would never cull against (or be culled by) its neighbours. Keep
		// re-measuring until the span is laid out, falling back to 50 meanwhile.
		if (!bo.labelTextWidth && labelHalo) {
			const span = labelHalo.nextElementSibling as HTMLElement | null;
			if (span && span.offsetWidth > 0) bo.labelTextWidth = span.offsetWidth;
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
		const textWidth = bo.labelTextWidth || 50;
		const c = ensureCandidate(_candidatesActive++);
		c.bodyId = body.data.id;
		c.bo = bo;
		c.body = body;
		c.label = label;
		c.labelHalo = labelHalo;
		c.isCapped =
			body.data.objectType === ObjectType.MOON
				? ctx.visibility.getMoonVisibility(body) === VISIBILITY.CAPPED
				: false;
		c.isMinor = bo.isMinor;
		c.isFocused = isFocused;
		c.isSelected = isFocused || isHovered;
		c.screenX = screenX;
		c.screenY = screenY;
		c.labelLeft = rootLeft;
		c.labelRight = rootLeft + 40 + textWidth;
		c.dist = bo.cachedDist;
	}

	// Sort the active prefix only — pooled slots past _candidatesActive must
	// stay quiescent, so we trim the array view and restore it after sort.
	_candidates.length = _candidatesActive;
	_candidates.sort((a, b) => {
		if (a.isSelected !== b.isSelected) return a.isSelected ? -1 : 1;
		const aMinor = a.isMinor && !a.isSelected;
		const bMinor = b.isMinor && !b.isSelected;
		if (aMinor !== bMinor) return aMinor ? 1 : -1;
		const pa = typePriority(a.body!.data.objectType);
		const pb = typePriority(b.body!.data.objectType);
		if (pa !== pb) return pa - pb;
		return a.dist - b.dist;
	});

	for (let i = 0; i < _candidatesActive; i++) {
		const c = _candidates[i];
		const labelHalo = c.labelHalo;
		const nameSpan = labelHalo?.nextElementSibling as HTMLElement | null;
		if (c.isCapped && !c.isSelected) {
			dimLabel(labelHalo, nameSpan, true);
			c.bo!.labelMaximized = false;
			continue;
		}
		// Check if behind a screen occluder (body large enough to hide labels behind it)
		if (
			!c.isSelected &&
			isScreenOccluded(c.screenX, c.screenY, c.dist, c.bodyId, screenOccluders)
		) {
			c.label!.visible = false;
			c.bo!.labelMaximized = false;
			continue;
		}
		// Minor-promoted, unselected: stays minimized at scale 0.5, but if a real
		// maximized halo (already in _accepted thanks to the sort) is sitting on
		// top of it, shrink further to 0.3 — the same "lost a conflict" visual a
		// maximized label gets. Tested against _accepted using the minor halo's
		// actual footprint (HALO_RADIUS_PX * 0.5), and never pushed into
		// _accepted so a minor halo can't block a real label.
		if (c.isMinor && !c.isSelected) {
			const minorRadius = HALO_RADIUS_PX * 0.5;
			let minorOverlaps = false;
			for (let j = 0; j < _acceptedActive; j++) {
				const a = _accepted[j];
				if (
					c.screenX - minorRadius < a.right &&
					c.screenX + minorRadius > a.left &&
					Math.abs(c.screenY - a.y) < LH
				) {
					minorOverlaps = true;
					break;
				}
			}
			dimLabel(labelHalo, nameSpan, !minorOverlaps, minorOverlaps ? 0.3 : 0.5);
			c.bo!.labelMaximized = false;
			continue;
		}
		let overlaps = false;
		for (let j = 0; j < _acceptedActive; j++) {
			const a = _accepted[j];
			if (c.labelLeft < a.right && c.labelRight > a.left && Math.abs(c.screenY - a.y) < LH) {
				overlaps = true;
				break;
			}
		}
		if (!overlaps) {
			const a = ensureAccepted(_acceptedActive++);
			a.left = c.labelLeft;
			a.right = c.labelRight;
			a.y = c.screenY;
			a.h = LH;
			restoreLabel(labelHalo, nameSpan, hoveredBodyIds.has(c.bodyId), c.isFocused);
			c.bo!.labelMaximized = true;
		} else {
			dimLabel(labelHalo, nameSpan, false);
			c.bo!.labelMaximized = false;
		}
	}

	// Release reference fields so the pool doesn't pin bodies/labels across
	// frames (e.g., when a promoted minor body is later unpromoted).
	for (let i = 0; i < _candidatesActive; i++) {
		const c = _candidates[i];
		c.bo = null;
		c.body = null;
		c.label = null;
		c.labelHalo = null;
	}
}

/**
 * Refresh `_accepted` with fresh-projected rects of every currently visible,
 * maximized body label. Runs every frame (the body cull above is throttled
 * to every 3rd) so the nomenclature cull sees up-to-date body rects — without
 * this, feature labels flicker for a few frames at the transition moment as
 * a body label slides over them, because the throttled accepted rects are
 * 0–2 frames stale and the feature overlap test "steps" between cull frames.
 * Dimmed and minor labels are excluded — their visual footprint is the small
 * halo, not the full text rect.
 */
export function refreshVisibleBodyLabelRects(
	bodyObjects: Map<string, BodyObjects>,
	screenWidth: number,
	screenHeight: number,
	camera: PerspectiveCamera,
	focusTruePos: [number, number, number]
): void {
	_acceptedActive = 0;
	for (const bo of bodyObjects.values()) {
		const { body, label } = bo;
		if (!label?.visible) continue;
		// `labelMaximized === false` only after the body cull explicitly dimmed
		// the label; undefined (never culled) is treated as maximized so freshly
		// appeared labels still cull features behind them.
		if (bo.labelMaximized === false) continue;
		const [bx, by, bz] = body.position;
		const lp = label.position;
		_tmpProj.set(
			bx - focusTruePos[0] + lp.x,
			by - focusTruePos[1] + lp.y,
			bz - focusTruePos[2] + lp.z
		);
		_tmpProj.project(camera);
		if (_tmpProj.z > 1) continue;
		const screenX = (_tmpProj.x * 0.5 + 0.5) * screenWidth;
		const screenY = (-_tmpProj.y * 0.5 + 0.5) * screenHeight;
		const rootLeft = screenX - label.center.x * 32;
		const textWidth = bo.labelTextWidth || 50;
		const a = ensureAccepted(_acceptedActive++);
		a.left = rootLeft;
		a.right = rootLeft + 40 + textWidth;
		a.y = screenY;
		a.h = LH;
	}
}
