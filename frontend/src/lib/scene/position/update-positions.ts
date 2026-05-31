import { Vector3 } from 'three';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';
import { applyOrientation } from '$lib/math/orientation';
import { orbitalElementsToPositionJD, parabolicToPositionJD } from '$lib/math/orbit/position';
import { sgp4PositionScene } from '$lib/math/orbit/sgp4';
import { OrbitalSource } from '$lib/fetch/position/format';
import { isLandedAt, probePositionKm } from '$lib/fetch/position/probes/propagate';
import { resolvePrimaryOverride } from '$lib/fetch/position/probes/primary';
import { populateProbeTrailBuffer } from '$lib/fetch/position/probes/trail';
import { getGmKm3s2 } from '$lib/fetch/systems-global';
import type { BodyObjects } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { FocusState } from '$lib/scene/animation/focus';
import type { Vec3 } from '$lib/scene/animation/math';
import {
	emptyGroup,
	updateOutOfRangeToast,
	type OutOfRangeState
} from '$lib/scene/out-of-range-toast';
import { refreshTrail } from '$lib/scene/objects/trail/refresh';
import { renderLandedProbe } from './landed-probe';
import type { PositionDiagnostics } from './diagnostics';

export interface UpdatePositionsParams {
	jd: number;
	ctx: ContextManager;
	bodyObjects: Map<string, BodyObjects>;
	focus: FocusState;
	focusedBody: PositionedBody | undefined;
	/** Caller-owned scratch Map; cleared and reused each call. */
	positionMap: Map<string, Vec3>;
	diagnostics: PositionDiagnostics;
}

/**
 * Per-frame body position + orientation update. Drives chebyshev, SPICE-probe,
 * SGP4, parabolic, and Keplerian paths; aggregates out-of-range bodies into a
 * single toast; locks focus onto the focused body's new position (unless an
 * animation is driving it); refreshes trail geometry against the new
 * focus basis. Invisible lines are marked `refreshDeferred` for the next pass.
 */
export function updatePositions(params: UpdatePositionsParams): void {
	const { jd, ctx, bodyObjects, focus, focusedBody, positionMap, diagnostics } = params;
	// Keep the chebyshev working set centred on `jd`. Fire-and-forget: the
	// frame may miss data for one or two ticks at a boundary, during which
	// chebyshev-tracked bodies are hidden (outOfRange) just like SGP4.
	ctx.chebStore?.ensure(jd);
	ctx.probeStore?.ensure(jd);

	// Probe zone preference: when the user is zoomed into a planet, prefer
	// that planet's zone over interplanetary so flyby probes (Psyche through
	// Mars, Voyager through Jupiter) resolve to the planet-relative fit and
	// their parentId flips to the planet barycenter — rendering correctly in
	// the active-system view instead of being hidden as Sun-orbiting bodies.
	// Null when zoomed out (no preference → interplanetary wins by default).
	const activeSysId = ctx.visibility.activeSystemId;
	const probeZonePreference = activeSysId
		? (fitCenterNaif: number) => ctx.bodies.isInSystem(`naif-${fitCenterNaif}`, activeSysId)
		: undefined;

	// Aggregate data-unavailability into a single summary toast — per-body
	// toasts would be spammy at chunk boundaries.
	const oorState: OutOfRangeState = {
		jd,
		satellites: emptyGroup(),
		majorBodies: emptyGroup(),
		focusedOutOfRange: false
	};
	const focusedId = focusedBody?.data.id;

	// Pre-seed last-known positions so a child reads the previous-frame value
	// (not [0,0,0]) when a parent early-returns. Seed stores body.position by
	// reference, so successful updates remain visible without re-seeding.
	positionMap.clear();
	positionMap.set('naif-0', [0, 0, 0]);
	for (const body of ctx.bodies.bodiesById.values()) {
		positionMap.set(body.data.id, body.position);
	}
	for (const bo of bodyObjects.values()) {
		if (!ctx.bodies.bodiesById.has(bo.body.data.id)) {
			positionMap.set(bo.body.data.id, bo.body.position);
		}
	}

	// Pass 1: compute positions + orbitCenters. Don't touch trail geometry
	// here — it depends on focus.focusTruePos, which can't be updated until
	// the focused body's own position is known below.
	const computePosition = (body: PositionedBody) => {
		const d = body.data;
		// `let` because the probe branch may re-parent (cruise → captured orbit
		// picks up under the planet's fit center) and the trail / trail-
		// anchor writes below need the resolved parent's position.
		let parentPos = positionMap.get(d.parentId) ?? ([0, 0, 0] as Vec3);
		const isParabolic = d.q != null;
		// Validity gate: hide SGP4/parabolic bodies outside their stated window.
		// Skipped for chebyshev (validityStart/End is the startup chunk's window,
		// not the full segment range) — its `positionScene` is the gate instead.
		const bo = bodyObjects.get(d.id);
		const isChebTracked = ctx.chebStore?.has(d.id) ?? false;
		const isProbe = d.orbitalSource === OrbitalSource.SPICE_PROBE;
		if (!isChebTracked && !isProbe && (jd < d.validityStart || jd > d.validityEnd)) {
			if (bo) bo.outOfRange = true;
			// SGP4 is the only source with a finite validity here (TLE epoch
			// ± 14 days); Keplerian/parabolic use ±Infinity bounds.
			if (d.satrec) {
				oorState.satellites.count++;
				if (d.validityStart < oorState.satellites.earliestStart) {
					oorState.satellites.earliestStart = d.validityStart;
				}
				if (d.validityEnd > oorState.satellites.latestEnd) {
					oorState.satellites.latestEnd = d.validityEnd;
				}
				if (d.id === focusedId) oorState.focusedOutOfRange = true;
			}
			return;
		}
		let x: number;
		let y: number;
		let z: number;
		if (isChebTracked) {
			// Chebyshev: polynomials only. No Kepler fallback — drifting into
			// extrapolated positions would break eclipse geometry.
			const chebOffset = ctx.chebStore!.positionScene(d.id, jd);
			if (!chebOffset) {
				if (bo) bo.outOfRange = true;
				// Only count as OOR-for-toast when jd is outside zone coverage;
				// inside coverage means a chunk is still loading (transient).
				const coverage = ctx.chebStore!.zoneCoverage(d.id);
				if (coverage && (jd < coverage.start || jd > coverage.end)) {
					oorState.majorBodies.count++;
					if (coverage.start < oorState.majorBodies.earliestStart) {
						oorState.majorBodies.earliestStart = coverage.start;
					}
					if (coverage.end > oorState.majorBodies.latestEnd) {
						oorState.majorBodies.latestEnd = coverage.end;
					}
					if (d.id === focusedId) oorState.focusedOutOfRange = true;
				}
				// Cascade-root diagnostic: when chebOffset is null for a major body,
				// any child whose own chebOffset is `[0,0,0]` lands at finite-zero
				// world coords this frame. Log once per body so we know which chunk
				// dropped out (positionMap pre-seed handles the child's own pos).
				diagnostics.warnOnce('cheb-null', d.id, () => {
					const insideCoverage = coverage ? jd >= coverage.start && jd <= coverage.end : undefined;
					const cov = coverage
						? `[${coverage.start.toFixed(1)},${coverage.end.toFixed(1)}]`
						: 'unknown';
					return (
						`chebStore.positionScene[${d.id}] returned null at jd=${jd.toFixed(3)} ` +
						`(coverage=${cov}, insideCoverage=${insideCoverage}) — children of this ` +
						`body will read stale positionMap entry (pre-seeded) instead of falling to SSB`
					);
				});
				return;
			}
			x = parentPos[0] + chebOffset[0];
			y = parentPos[1] + chebOffset[1];
			z = parentPos[2] + chebOffset[2];
		} else if (isProbe) {
			// Probes dispatch per sub-chunk inside the store. Fit center is the
			// zone's `fit_center_naif_id` — NOT d.parentId (which lags by a frame
			// at cross-zone transitions). Re-resolve per frame, then flip parentId
			// so trail geometry and trail-anchor writes follow the new parent.
			const located = ctx.probeStore?.probeWithCenter(d.id, jd, probeZonePreference) ?? null;
			if (!located) {
				if (bo) bo.outOfRange = true;
				if (d.id === focusedId) oorState.focusedOutOfRange = true;
				diagnostics.warnOnce('probe-unavailable', d.id, () => {
					const reason = !ctx.probeStore
						? 'no ProbeStore'
						: 'no zone has both a loaded chunk and a sub-chunk covering this jd';
					return `probe ${d.id} (${d.name ?? 'unnamed'}): hidden — ${reason}`;
				});
				return;
			}
			// Landed branch: place at lat/lng on the landing body's surface,
			// applying its IAU orientation. Skip the flying-fit path entirely.
			const probeLanded = located.probe.landed;
			if (probeLanded && isLandedAt(located.probe, jd)) {
				const landedRender = renderLandedProbe(d, located.probe, probeLanded, jd, positionMap, ctx);
				if (!landedRender) {
					if (bo) bo.outOfRange = true;
					if (d.id === focusedId) oorState.focusedOutOfRange = true;
					return;
				}
				diagnostics.clear('probe-unavailable', d.id);
				if (bo) bo.outOfRange = false;
				body.position[0] = landedRender.x;
				body.position[1] = landedRender.y;
				body.position[2] = landedRender.z;
				if (body.orbitCenter) {
					body.orbitCenter[0] = landedRender.parentPos[0];
					body.orbitCenter[1] = landedRender.parentPos[1];
					body.orbitCenter[2] = landedRender.parentPos[2];
				}
				if (body.trailAnchor) {
					body.trailAnchor[0] = landedRender.parentPos[0];
					body.trailAnchor[1] = landedRender.parentPos[1];
					body.trailAnchor[2] = landedRender.parentPos[2];
				}
				positionMap.set(d.id, body.position);
				return;
			}
			// Resolve the probe's stamped primary (Moon for lunar orbiters,
			// Titan for Cassini-at-Titan, …) or fall back to the zone center.
			// Sub-chunks are fit against THAT body, so the propagator's mu
			// must match.
			const zoneCenterKey = `naif-${located.fitCenterNaifId}`;
			const rawOverride = resolvePrimaryOverride(
				located.probe,
				jd,
				zoneCenterKey,
				ctx.chebStore ?? null
			);
			const overridePos = rawOverride ? positionMap.get(rawOverride.id) : undefined;
			const useOverride = !!(rawOverride && overridePos);
			const probeParentKey = useOverride ? rawOverride!.id : zoneCenterKey;
			const probePrimaryNaif = useOverride ? rawOverride!.naifId : located.fitCenterNaifId;
			const primaryMu = getGmKm3s2(probePrimaryNaif) ?? 0;
			const probeOffsetKm = probePositionKm(located.probe, jd, primaryMu);
			if (!probeOffsetKm) {
				if (bo) bo.outOfRange = true;
				if (d.id === focusedId) oorState.focusedOutOfRange = true;
				diagnostics.warnOnce(
					'probe-unavailable',
					d.id,
					() =>
						`probe ${d.id} (${d.name ?? 'unnamed'}): hidden — sub-chunk evaluation returned ` +
						'null (uncoverable, non-finite fit, or missing mu for kepler_pure)'
				);
				return;
			}
			diagnostics.clear('probe-unavailable', d.id);
			// Reseed the trail buffer (when present) before flipping parentId,
			// so the back-population samples against the OLD parent's frame are
			// dropped and the new frame starts fresh. Skip on first-ever resolve
			// (initial parentId was set by processProbes against the same
			// parent) — only the live mid-play flip needs a clear.
			const probeParentChanged = d.parentId !== probeParentKey;
			if (probeParentChanged && body.trailBuffer && ctx.probeStore) {
				body.trailBuffer.clear();
				populateProbeTrailBuffer(
					body.trailBuffer,
					ctx.probeStore,
					ctx.chebStore ?? null,
					d.id,
					probeParentKey,
					jd,
					probeZonePreference
				);
			}
			if (probeParentChanged) d.parentId = probeParentKey;
			parentPos = positionMap.get(probeParentKey) ?? ([0, 0, 0] as Vec3);
			const probeOffsetX = kmToScene(probeOffsetKm[0]);
			const probeOffsetY = kmToScene(probeOffsetKm[2]);
			const probeOffsetZ = -kmToScene(probeOffsetKm[1]);
			x = parentPos[0] + probeOffsetX;
			y = parentPos[1] + probeOffsetY;
			z = parentPos[2] + probeOffsetZ;
			// Trail-buffer maintenance: append at canonical stepDays intervals
			// since the last sample. A backwards jump or a gap > capacity*step
			// invalidates the existing samples — reseed via back-populate so
			// the trail comes back instantly instead of growing from empty.
			const tb = body.trailBuffer;
			if (tb) {
				const last = tb.newestJd;
				const dt = jd - last;
				const span = tb.stepDays * tb.capacity;
				if (isFinite(last) && (dt < 0 || dt > span) && ctx.probeStore) {
					tb.clear();
					populateProbeTrailBuffer(
						tb,
						ctx.probeStore,
						ctx.chebStore ?? null,
						d.id,
						probeParentKey,
						jd,
						probeZonePreference
					);
				} else if (!isFinite(tb.newestJd) || jd - tb.newestJd >= tb.stepDays) {
					tb.append(jd, probeOffsetX, probeOffsetY, probeOffsetZ);
				}
			}
		} else if (d.a === 0 && !isParabolic && !d.satrec) {
			// Body coincides with its parent (Kepler-only barycenter placeholder).
			[x, y, z] = parentPos;
		} else {
			const offset = d.satrec
				? sgp4PositionScene(d.satrec, jd)
				: isParabolic
					? parabolicToPositionJD(d, jd)
					: orbitalElementsToPositionJD(d, jd);
			if (!offset) return;
			x = parentPos[0] + offset[0];
			y = parentPos[1] + offset[1];
			z = parentPos[2] + offset[2];
		}
		if (bo) bo.outOfRange = false;
		body.position[0] = x;
		body.position[1] = y;
		body.position[2] = z;
		if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) {
			diagnostics.warnOnce('non-finite', d.id, () => {
				const parentInMap = positionMap.has(d.parentId);
				return (
					`computePosition[${d.id}] non-finite: pos=[${x},${y},${z}] ` +
					`parentId=${d.parentId} parentInPositionMap=${parentInMap} ` +
					`parentPos=[${parentPos[0]},${parentPos[1]},${parentPos[2]}] ` +
					`isChebTracked=${isChebTracked} isProbe=${isProbe} objectType=${d.objectType}`
				);
			});
		}
		if (body.orbitCenter) {
			body.orbitCenter[0] = parentPos[0];
			body.orbitCenter[1] = parentPos[1];
			body.orbitCenter[2] = parentPos[2];
		}
		if (body.trailAnchor) {
			body.trailAnchor[0] = parentPos[0];
			body.trailAnchor[1] = parentPos[1];
			body.trailAnchor[2] = parentPos[2];
		}
		positionMap.set(d.id, body.position);

		if (!bo) return;
		if (bo.trail && body.orbitCenter) {
			const oc = bo.trail.userData.orbitCenter as Vector3 | undefined;
			if (oc) oc.set(parentPos[0], parentPos[1], parentPos[2]);
		}
		if (body.orientation && bo.mesh) {
			applyOrientation(bo.mesh, body.orientation, jd, body.nutPrec);
		}
		// Rings inherit the planet's pole orientation (geometry pre-rotated so
		// local +Y is the pole). Re-apply each frame so nutation/precession/spin
		// stay in sync with the planet.
		if (body.orientation && bo.rings) {
			applyOrientation(bo.rings.mesh, body.orientation, jd, body.nutPrec);
		}
	};

	// First pass: bodies in ctx.bodies.bodiesById (barycenters → planets → moons).
	// Second pass: promoted minor bodies that only live in bodyObjects.
	//
	// Skip moons outside the focused system: their visuals are all gated on
	// `isInFocusedSystem`, so a stale position can't render, and switching
	// focus pulls them back in the same frame `focusedSystemId` flips.
	const sysId = ctx.visibility.focusedSystemId;
	for (const body of ctx.bodies.bodiesById.values()) {
		if (body.data.objectType === ObjectType.MOON) {
			const inSystem = sysId !== null && body.data.parentId === sysId;
			if (!inSystem && body.data.id !== focusedId) {
				// Seed positionMap with the last-computed position so any child
				// (e.g. a sub-moon spacecraft) resolves to the stale-but-known
				// parent location instead of origin.
				positionMap.set(body.data.id, body.position);
				continue;
			}
		}
		computePosition(body);
	}
	for (const bo of bodyObjects.values()) {
		if (!ctx.bodies.bodiesById.has(bo.body.data.id)) computePosition(bo.body);
	}

	updateOutOfRangeToast(oorState);

	// Lock focus onto the focused body's new position unless an animation is
	// driving it. Also refresh body-relative camera target so the fly
	// destination tracks the moving body.
	if (focusedBody) {
		const p = focusedBody.position;
		const elapsed = performance.now() - focus.focusStartTime;
		const animating = elapsed < focus.focusDurationMs;
		focus.focusTargetWorld[0] = p[0];
		focus.focusTargetWorld[1] = p[1];
		focus.focusTargetWorld[2] = p[2];
		const camOff = focus.camTargetOffset;
		if (camOff && focus.camTargetWorld) {
			focus.camTargetWorld[0] = p[0] + camOff[0];
			focus.camTargetWorld[1] = p[1] + camOff[1];
			focus.camTargetWorld[2] = p[2] + camOff[2];
		}
		if (!animating) {
			focus.focusTruePos[0] = p[0];
			focus.focusTruePos[1] = p[1];
			focus.focusTruePos[2] = p[2];
		}
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
		refreshTrail(bo.body, line, basis, jd);
		line.userData.refreshDeferred = false;
	}
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
	jd: number
): void {
	const basis = focus.focusTruePos;
	for (const bo of bodyObjects.values()) {
		const line = bo.trail;
		if (!line || !line.visible || !line.userData.refreshDeferred) continue;
		refreshTrail(bo.body, line, basis, jd);
		line.userData.refreshDeferred = false;
	}
}
