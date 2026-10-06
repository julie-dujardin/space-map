import { ObjectType, type PositionedBody, type Unplaced } from '$lib/types/objects';
import type { BodyObjects } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { FocusState } from '$lib/scene/animation/focus';
import type { Vec3 } from '$lib/scene/animation/math';
import type { OutOfRangeNotifier } from '$lib/scene/out-of-range-notice';
import { refreshTrail, type TrailView } from '$lib/scene/objects/trail/refresh';
import type { Placer } from './placer';

export interface UpdatePositionsParams {
	jd: number;
	ctx: ContextManager;
	bodyObjects: Map<string, BodyObjects>;
	focus: FocusState;
	focusedBody: PositionedBody | undefined;
	placer: Placer;
	/** Camera for the trail rewrite gate; absent = rewrite every visible trail. */
	trailView?: TrailView;
	/** Frame counter for the hidden-body stagger; absent = move every body. */
	frame?: number;
	/** Reports the data-coverage notice for this map. */
	outOfRange: OutOfRangeNotifier;
}

export interface UpdatePositionsResult {
	/** The focused body has no place at this date. */
	focusUnplaced: boolean;
	/** Nearest placed ancestor the camera follows in its stead, or null. */
	anchorId: string | null;
}

/** Reasons the notice reports. `never` has its own message, and `loading` ends by itself. */
const NOTICE_REASONS: ReadonlySet<Unplaced> = new Set(['not-yet', 'no-data', 'parent', 'failed']);

/**
 * Per-frame pass: places the bodies the scene draws, reports missing data in
 * one notice, keeps the camera on the focused body, and refreshes the trails
 * against the new focus basis.
 */
export function updatePositions(params: UpdatePositionsParams): UpdatePositionsResult {
	const { jd, ctx, bodyObjects, focus, focusedBody, placer, trailView, frame, outOfRange } = params;
	// Keep the ephemeris working sets centred on `jd`. A body whose chunk is not
	// there yet has no place for a frame or two.
	ctx.chebStore?.ensure(jd);
	ctx.probeStore?.ensure(jd);

	// Where the focus chain was before this pass: the camera follows the
	// displacement of an ancestor when the focus itself has no place.
	const ancestors: { body: PositionedBody; oldPos: Vec3 | null }[] = [];
	if (focusedBody) {
		const seen = new Set<string>([focusedBody.data.id]);
		let cur = ctx.getBody(focusedBody.data.parentId);
		while (cur && !seen.has(cur.data.id)) {
			seen.add(cur.data.id);
			ancestors.push({ body: cur, oldPos: cur.position ? [...cur.position] : null });
			cur = ctx.getBody(cur.data.parentId);
		}
	}

	placer.begin(jd, focusedBody?.data.id, frame);
	// Moons outside the focused system are not drawn: `place` settles one when
	// something reads it.
	const sysId = ctx.visibility.focusedSystemId;
	for (const body of ctx.bodies.bodiesById.values()) {
		if (
			body.data.objectType === ObjectType.MOON &&
			body.data.parentId !== sysId &&
			body !== focusedBody
		) {
			continue;
		}
		placer.placeInPass(body);
	}
	for (const bo of bodyObjects.values()) placer.placeInPass(bo.body);
	// A surface feature is in neither store.
	const focusPos = focusedBody ? placer.place(focusedBody, jd) : null;

	const why = focusedBody?.unplaced;
	outOfRange.update({
		jd,
		satellites: ctx.refresher?.satelliteCoverage(jd) ?? { kind: 'covered' },
		majorBodies: placer.noData,
		focusedOutOfRange: why !== undefined && NOTICE_REASONS.has(why)
	});

	// Lock the camera frame onto the focused body unless an animation drives it.
	let anchorId: string | null = null;
	const animating = performance.now() - focus.focusStartTime < focus.focusDurationMs;
	if (focusedBody && !focusPos) {
		// The focus stays on the body. The camera follows its nearest placed
		// ancestor, so it does not freeze in world space.
		for (const a of ancestors) {
			const p = placer.place(a.body, jd);
			if (!p) continue;
			anchorId = a.body.data.id;
			if (animating) {
				// A pan onto the anchor is running: keep its look target on the anchor.
				setVec(focus.focusTargetWorld, p);
				const camOff = focus.camTargetOffset;
				if (camOff && focus.camTargetWorld) addVec(focus.camTargetWorld, p, camOff);
			} else if (a.oldPos) {
				// Idle: shift the camera frame by the displacement of the anchor.
				focus.focusTruePos[0] += p[0] - a.oldPos[0];
				focus.focusTruePos[1] += p[1] - a.oldPos[1];
				focus.focusTruePos[2] += p[2] - a.oldPos[2];
				setVec(focus.focusTargetWorld, focus.focusTruePos);
			}
			break;
		}
	} else if (focusPos) {
		setVec(focus.focusTargetWorld, focusPos);
		const camOff = focus.camTargetOffset;
		if (camOff && focus.camTargetWorld) addVec(focus.camTargetWorld, focusPos, camOff);
		// Arc-orbit only: pin the start of the arc to the body too, so the body stays framed.
		const camOrigOff = focus.camOriginOffset;
		if (camOrigOff && focus.camOriginWorld) addVec(focus.camOriginWorld, focusPos, camOrigOff);
		if (!animating) setVec(focus.focusTruePos, focusPos);
	}

	// Refresh trails against the fresh focus basis. Doing it inside computePosition
	// would shift trails by focus-velocity * dt. Invisible lines defer to
	// {@link refreshDeferredTrails} to avoid GPU uploads for off-screen trails.
	const basis = focus.focusTruePos;
	for (const bo of bodyObjects.values()) {
		const line = bo.trail;
		if (!line) continue;
		if (!line.visible) {
			line.userData.refreshDeferred = true;
			continue;
		}
		refreshTrail(bo.body, line, basis, jd, trailView);
		line.userData.refreshDeferred = false;
	}

	return { focusUnplaced: focusedBody !== undefined && !focusPos, anchorId };
}

/**
 * Refresh trails marked `refreshDeferred` by {@link updatePositions} —
 * i.e. lines that were invisible last frame but just got flipped visible by
 * `updateBodyVisibility`. Without this they'd render against a stale basis
 * for one frame.
 */
export function refreshDeferredTrails(
	bodyObjects: Map<string, BodyObjects>,
	focus: FocusState,
	jd: number,
	trailView?: TrailView
): void {
	const basis = focus.focusTruePos;
	for (const bo of bodyObjects.values()) {
		const line = bo.trail;
		if (!line || !line.visible || !line.userData.refreshDeferred) continue;
		refreshTrail(bo.body, line, basis, jd, trailView);
		line.userData.refreshDeferred = false;
	}
}

function setVec(out: Vec3, v: Readonly<Vec3>): void {
	out[0] = v[0];
	out[1] = v[1];
	out[2] = v[2];
}

function addVec(out: Vec3, a: Readonly<Vec3>, b: Readonly<Vec3>): void {
	out[0] = a[0] + b[0];
	out[1] = a[1] + b[1];
	out[2] = a[2] + b[2];
}
