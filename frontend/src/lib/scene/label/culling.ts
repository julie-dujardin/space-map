import { Vector3, type PerspectiveCamera } from 'three';
import { ObjectType } from '$lib/types/objects';
import { ndcZVisible } from '$lib/scene/setup/depth-mode';
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
 * A body large enough to hide labels behind it, tested via its tangent cone —
 * exact even when the limb crosses the camera plane or the body is an oblate
 * ellipsoid. Precomputed in the space where the body is a unit sphere so
 * {@link isScreenOccluded} rebuilds the label's view ray without reprojecting.
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
	/** Body center in camera space — feeds the perspective-horizon depth test. */
	ccx: number;
	ccy: number;
	ccz: number;
};

export function dimLabel(
	labelHalo: HTMLElement | null,
	nameSpan: HTMLElement | null,
	clickable: boolean,
	scale = 0.3,
	subSpan: HTMLElement | null = null
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
	// The credit line captions the name; alone next to a collapsed halo it
	// reads as a body called "Carried by Cassini".
	if (subSpan) subSpan.style.display = 'none';
}

export function restoreLabel(
	labelHalo: HTMLElement | null,
	nameSpan: HTMLElement | null,
	isHovered: boolean,
	isFocused: boolean,
	subSpan: HTMLElement | null = null
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
	if (subSpan) subSpan.style.display = '';
}

/**
 * Applies label visibility for a body, handling the close-in case where the
 * rendered sphere is large enough to replace the halo indicator. Returns true
 * on hidden→visible transitions so the caller can force an immediate cull
 * instead of a 1–2 frame flash of un-culled labels.
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

	// noPhysical bodies have no disc — halo never yields to a sphere, label stays centered.
	const screenR = !bo.noPhysical && radiusScene > 0 ? (radiusScene / distToBody) * projScale : 0;
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
	// Once the disc replaces the halo, the name is anchored on the right limb. If
	// that limb has left the viewport the name would be off screen anyway (the body
	// fills the view or sits past the right edge) — drop it.
	if (hideHaloRing && bo.labelAnchorOffscreen) show = false;
	if (bo.trail && hideHaloRing) bo.trail.visible = false;

	label.visible = show;
	if (labelHalo) labelHalo.style.visibility = hideHaloRing ? 'hidden' : '';
	// Loader DOM node only exists while a model is loading (managed by
	// `setHaloLoading`). Show it exactly when the halo would be hidden by
	// the close-zoom rule — it sits at the viewport centre.
	if (bo.loadingEl) bo.loadingEl.style.display = hideHaloRing ? '' : 'none';
	// The anchor already sits on the near limb (see updateBodyVisibility); the name
	// only needs a small fixed gap past it — 4px clear of the 32px halo box, always
	// to the right (may run off screen, which is fine).
	label.center.x = hideHaloRing ? 1 - 4 / 32 : 0.5;
	return show && !wasVisible;
}

/** True when a screen point falls inside a closer occluder's silhouette cone. */
export function isScreenOccluded(
	sx: number,
	sy: number,
	dist: number,
	selfId: string,
	occluders: readonly ScreenOccluder[]
): boolean {
	for (const occ of occluders) {
		if (occ.id === selfId) continue;
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
		if (root * root <= occ.K * (p * p + q * q + s * s)) continue; // outside the silhouette cone
		// Within the silhouette, hide only if the label is on the body's FAR cap.
		// Keys off the label's own distance (not the occluder's mean radius) so it
		// stays exact regardless of relief. Camera-space visible-cap test
		// C·(P−C) > 0 with P = dist·d̂ reduces to hide when C·d ≤ dist·|d|.
		const cd = u * occ.ccx + v * occ.ccy + w * occ.ccz;
		if (cd <= dist * Math.hypot(u, v, w)) return true;
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

/** Screen space spoken for before any cull runs — the trip planner's
 *  trajectory labels are the map's content while a trip is being chosen, so
 *  they're seeded into the accepted set ahead of everything and never culled. */
const _reserved: AcceptedRect[] = [];
let _reservedActive = 0;

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

/** Hold `count` rects out of every cull this frame; 0 releases them. Called
 *  before the culls run, by whatever owns labels that outrank the scene's own. */
export function reserveLabelRects(rects: readonly AcceptedRect[], count: number): void {
	_reservedActive = 0;
	for (let i = 0; i < count; i++) {
		const r = rects[i];
		let a = _reserved[i];
		if (!a) {
			a = { left: 0, right: 0, y: 0, h: 0 };
			_reserved[i] = a;
		}
		a.left = r.left;
		a.right = r.right;
		a.y = r.y;
		a.h = r.h;
		_reservedActive++;
	}
}

/** Open an accepted set with the reserved rects already in it, and answer how
 *  many slots that used. */
function seedAccepted(): number {
	for (let i = 0; i < _reservedActive; i++) {
		const r = _reserved[i];
		const a = ensureAccepted(i);
		a.left = r.left;
		a.right = r.right;
		a.y = r.y;
		a.h = r.h;
	}
	return _reservedActive;
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
	_acceptedActive = seedAccepted();

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
		if (!ndcZVisible(_tmpProj.z)) continue;
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
			dimLabel(labelHalo, nameSpan, true, 0.3, c.bo!.labelSub);
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
			dimLabel(labelHalo, nameSpan, !minorOverlaps, minorOverlaps ? 0.3 : 0.5, c.bo!.labelSub);
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
			restoreLabel(labelHalo, nameSpan, hoveredBodyIds.has(c.bodyId), c.isFocused, c.bo!.labelSub);
			c.bo!.labelMaximized = true;
		} else {
			dimLabel(labelHalo, nameSpan, false, 0.3, c.bo!.labelSub);
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
 * Refresh `_accepted` with fresh-projected rects of every visible, maximized
 * body label, every frame — the body cull above is throttled to every 3rd, so
 * without this the nomenclature cull sees stale rects and feature labels
 * flicker as a body label slides over them. Dimmed/minor labels are excluded:
 * their footprint is the small halo, not the full text rect.
 */
export function refreshVisibleBodyLabelRects(
	bodyObjects: Map<string, BodyObjects>,
	screenWidth: number,
	screenHeight: number,
	camera: PerspectiveCamera,
	focusTruePos: [number, number, number]
): void {
	_acceptedActive = seedAccepted();
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
		if (!ndcZVisible(_tmpProj.z)) continue;
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
