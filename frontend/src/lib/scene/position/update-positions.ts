import { Quaternion, Vector3 } from 'three';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';
import {
	applyOrientation,
	applyPointing,
	applySouthTowardParent,
	type PointingSpec
} from '$lib/math/orientation';
import { isModelBearing } from '$lib/scene/objects/body/model';
import { SUN_ID } from '$lib/constants';
import { orbitalElementsToPositionJD, parabolicToPositionJD } from '$lib/math/orbit/position';
import { sgp4PositionScene } from '$lib/math/orbit/sgp4';
import { OrbitalSource } from '$lib/fetch/position/format';
import { isLandedAt, probePositionKm } from '$lib/fetch/position/probes/propagate';
import { resolvePrimaryOverride } from '$lib/fetch/position/probes/primary';
import { populateProbeTrailBuffer } from '$lib/fetch/position/probes/trail';
import {
	ADAPTIVE_MAX_STEP_FACTOR,
	ADAPTIVE_MIN_STEP_FACTOR
} from '$lib/fetch/position/trail-buffer';
import { getGmKm3s2 } from '$lib/fetch/systems-global';
import { J2000_JD } from '$lib/time/jd';
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
import { setSpacecraftLanded } from '$lib/scene/label/factory';
import type { PositionDiagnostics } from './diagnostics';

/** Module-scope scratch for adaptive trail chord-error sampling. JS is single-
 *  threaded and the buffer is consumed within one probe iteration, so reusing
 *  one allocation across all probes per frame is safe and avoids GC churn. */
const newestPosScratch: [number, number, number] = [0, 0, 0];

/** Scratch for the focused probe's attitude quaternion (one body per frame). */
const attitudeQuat = new Quaternion();

/** Last world position per body for `velocity`-target pointing. Only the focused
 *  model carries a pointing spec, so this stays tiny. */
const velCache = new Map<
	string,
	{ jd: number; pos: [number, number, number]; dir: [number, number, number] | null }
>();

function needsVelocity(spec: PointingSpec): boolean {
	return spec.primary.target === 'velocity' || spec.secondary?.target === 'velocity';
}

/** Finite-difference world velocity direction; source-agnostic. Reuses the last
 *  good direction while paused (dt = 0); undefined until two distinct-jd samples
 *  exist. Sign-corrected so reverse playback still yields the prograde heading. */
function estimateVelocity(
	id: string,
	jd: number,
	pos: readonly [number, number, number]
): [number, number, number] | undefined {
	const prev = velCache.get(id);
	let dir = prev?.dir ?? null;
	if (prev && jd !== prev.jd) {
		const s = Math.sign(jd - prev.jd);
		const vx = (pos[0] - prev.pos[0]) * s;
		const vy = (pos[1] - prev.pos[1]) * s;
		const vz = (pos[2] - prev.pos[2]) * s;
		const len = Math.hypot(vx, vy, vz);
		if (len > 1e-12) dir = [vx / len, vy / len, vz / len];
	}
	velCache.set(id, { jd, pos: [pos[0], pos[1], pos[2]], dir });
	return dir ?? undefined;
}

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

export interface UpdatePositionsResult {
	/** Focused body had no data at this jd (hidden). */
	focusedOutOfRange: boolean;
	/** Nearest in-range ancestor the camera was re-anchored to, or null. */
	reanchorId: string | null;
}

/**
 * Per-frame body position + orientation update. Drives chebyshev, SPICE-probe,
 * SGP4, parabolic, and Keplerian paths; aggregates out-of-range bodies into a
 * single toast; locks focus onto the focused body's new position (unless an
 * animation is driving it); refreshes trail geometry against the new
 * focus basis. Invisible lines are marked `refreshDeferred` for the next pass.
 */
export function updatePositions(params: UpdatePositionsParams): UpdatePositionsResult {
	const { jd, ctx, bodyObjects, focus, focusedBody, positionMap, diagnostics } = params;
	// Keep the chebyshev working set centred on `jd`. Fire-and-forget: the
	// frame may miss data for one or two ticks at a boundary, during which
	// chebyshev-tracked bodies are hidden (outOfRange) just like SGP4.
	ctx.chebStore?.ensure(jd);
	ctx.probeStore?.ensure(jd);

	// When zoomed into a planet, prefer its zone over interplanetary so flyby
	// probes (Psyche → Mars, Voyager → Jupiter) take the planet-relative fit
	// and flip parentId to the planet. Null = no preference, interplanetary
	// wins by default.
	const activeSysId = ctx.visibility.activeSystemId;
	const probeZonePreference = activeSysId
		? (fitCenterNaif: number) => ctx.bodies.isInSystem(`naif-${fitCenterNaif}`, activeSysId)
		: undefined;

	// Aggregate data-unavailability into a single summary toast — per-body
	// toasts would be spammy at chunk boundaries.
	const oorState: OutOfRangeState = {
		jd,
		// Resolved from zone metadata after the loop; per-body validity only hides
		// sats, it doesn't drive the toast.
		satellites: { kind: 'covered' },
		majorBodies: emptyGroup(),
		focusedOutOfRange: false
	};
	const focusedId = focusedBody?.data.id;

	// Snapshot the focus's orbit-ancestor positions before computePosition
	// overwrites them; the focus-sync block re-anchors off these when the focus
	// goes out of range across a time jump.
	const focusAncestors: { id: string; oldPos: Vec3; bo: BodyObjects | undefined }[] = [];
	if (focusedBody) {
		const seen = new Set<string>([focusedBody.data.id]);
		let cur = ctx.getBody(focusedBody.data.parentId);
		while (cur && !seen.has(cur.data.id)) {
			seen.add(cur.data.id);
			focusAncestors.push({
				id: cur.data.id,
				oldPos: [cur.position[0], cur.position[1], cur.position[2]],
				bo: bodyObjects.get(cur.data.id)
			});
			cur = ctx.getBody(cur.data.parentId);
		}
	}

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
		const bo = bodyObjects.get(d.id);
		const isChebTracked = ctx.chebStore?.has(d.id) ?? false;
		const isProbe = d.orbitalSource === OrbitalSource.SPICE_PROBE;
		// Discovery gate: hide a body before it came into existence (moon/sat
		// discovery or launch). NaN/undefined visibleFromDays = always visible.
		// outOfRange hides the mesh + label; writeMoons() drops the dot too.
		if (d.visibleFromDays !== undefined && jd - J2000_JD < d.visibleFromDays) {
			if (bo) bo.outOfRange = true;
			if (d.id === focusedId) oorState.focusedOutOfRange = true;
			return;
		}
		// Probes re-resolve their fit center below (cruise → captured orbit can
		// flip parentId), so let the probe branch handle parent lookup; for
		// everything else, the parent must be in the per-frame positionMap. A
		// miss means the parent isn't tracked this frame (e.g. URL-loaded a
		// moon-of-asteroid before the host's chunk lands, or the host lives in
		// `asteroidBodiesByZone` which the frame loop doesn't pre-seed). Hide
		// rather than fall back to SSB — anchoring at the origin places
		// asteroid-moons at the Sun.
		let parentPos: Vec3;
		if (isProbe) {
			parentPos = positionMap.get(d.parentId) ?? ([0, 0, 0] as Vec3);
		} else {
			const lookup = positionMap.get(d.parentId);
			if (!lookup) {
				if (bo) bo.outOfRange = true;
				if (d.id === focusedId) oorState.focusedOutOfRange = true;
				diagnostics.warnOnce(
					'missing-parent',
					d.id,
					() => `computePosition[${d.id}]: parent ${d.parentId} not in positionMap — hiding`
				);
				return;
			}
			parentPos = lookup;
			diagnostics.clear('missing-parent', d.id);
		}
		const isParabolic = d.q != null;
		// Validity gate: hide SGP4/parabolic bodies outside their stated window.
		// Skipped for chebyshev (validityStart/End is the startup chunk's window,
		// not the full segment range) — its `positionScene` is the gate instead.
		if (!isChebTracked && !isProbe && (jd < d.validityStart || jd > d.validityEnd)) {
			if (bo) bo.outOfRange = true;
			// Hide the sat; the group toast comes from zone coverage below, not a
			// stale chunk. Only SGP4 has finite validity (Keplerian/parabolic ±Inf).
			if (d.satrec && d.id === focusedId) oorState.focusedOutOfRange = true;
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
				const landedRender = renderLandedProbe(
					d,
					located.probe,
					probeLanded,
					jd,
					positionMap,
					ctx,
					bodyObjects
				);
				if (!landedRender) {
					if (bo) bo.outOfRange = true;
					if (d.id === focusedId) oorState.focusedOutOfRange = true;
					return;
				}
				diagnostics.clear('probe-unavailable', d.id);
				if (bo) {
					bo.outOfRange = false;
					if (!bo.isLanded) {
						setSpacecraftLanded(bo.labelHalo, true);
						bo.isLanded = true;
					}
				}
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
				// Stand the lander on the terrain: aim its south pole (−Y) at the
				// body centre so it sits upright (nadir), roll free.
				if (bo?.mesh) applySouthTowardParent(bo.mesh, body.position, landedRender.parentPos);
				if (bo?.model) applySouthTowardParent(bo.model, body.position, landedRender.parentPos);
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
			if (bo?.isLanded) {
				setSpacecraftLanded(bo.labelHalo, false);
				bo.isLanded = false;
			}
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
					jd
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
			// Trail-buffer maintenance: append the current sample when chord
			// error from the last sample exceeds the buffer's tolerance, so the
			// polyline densifies near periapsis/gravity assists and stays sparse
			// near apoapsis. Bracketed by minStep/maxStep to avoid degenerate
			// cases (over-fine subdivision near singularities, sparse cruise
			// arcs). A backwards jump or a gap > one full span invalidates the
			// existing samples — reseed via back-populate so the trail comes
			// back instantly instead of growing from empty.
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
						jd
					);
				} else if (!isFinite(last)) {
					tb.append(jd, probeOffsetX, probeOffsetY, probeOffsetZ);
				} else if (isFinite(tb.epsilonScene)) {
					const maxStep = tb.stepDays * ADAPTIVE_MAX_STEP_FACTOR;
					const minStep = tb.stepDays * ADAPTIVE_MIN_STEP_FACTOR;
					if (dt >= maxStep) {
						tb.append(jd, probeOffsetX, probeOffsetY, probeOffsetZ);
					} else if (dt >= minStep && tb.readNewestPos(newestPosScratch)) {
						const midKm = probePositionKm(located.probe, (last + jd) / 2, primaryMu);
						if (midKm) {
							const midX = kmToScene(midKm[0]);
							const midY = kmToScene(midKm[2]);
							const midZ = -kmToScene(midKm[1]);
							const cx = (newestPosScratch[0] + probeOffsetX) / 2;
							const cy = (newestPosScratch[1] + probeOffsetY) / 2;
							const cz = (newestPosScratch[2] + probeOffsetZ) / 2;
							const ex = midX - cx;
							const ey = midY - cy;
							const ez = midZ - cz;
							const eps = tb.epsilonScene;
							if (ex * ex + ey * ey + ez * ez > eps * eps) {
								tb.append(jd, probeOffsetX, probeOffsetY, probeOffsetZ);
							}
						}
					}
				} else if (dt >= tb.stepDays) {
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
		if (body.orientation && (bo.mesh || bo.model)) {
			if (bo.mesh) applyOrientation(bo.mesh, body.orientation, jd, body.nutPrec);
			// Natural-body shape model shares the sphere's IAU spin. It's a
			// modelScene child (identity parent → world==local), so only the
			// quaternion is needed; the overlay seats its position. The label
			// anchor co-rotates so surface features stay pinned to the model.
			if (bo.model) applyOrientation(bo.model, body.orientation, jd, body.nutPrec);
			if (bo.nomenclatureAnchor)
				applyOrientation(bo.nomenclatureAnchor, body.orientation, jd, body.nutPrec);
		} else if (isModelBearing(body)) {
			// Sats/probes have no IAU data. Priority: debug override > CK attitude
			// track (within coverage) > pointing spec > nadir at the parent. Sphere
			// and overlay model share the attitude.
			const track = body.attitudeTrack;
			if (!body.pointingOverride && track && track.orientationAt(jd, attitudeQuat)) {
				if (bo.mesh) bo.mesh.quaternion.copy(attitudeQuat);
				if (bo.model) bo.model.quaternion.copy(attitudeQuat);
			} else {
				const spec = body.pointingOverride ?? body.pointing;
				if (spec) {
					const velocity = needsVelocity(spec)
						? estimateVelocity(d.id, jd, body.position)
						: undefined;
					const pctx = {
						bodyPos: body.position,
						parentPos,
						sunPos: positionMap.get(SUN_ID),
						velocity
					};
					if (bo.mesh) applyPointing(bo.mesh, spec, pctx);
					if (bo.model) applyPointing(bo.model, spec, pctx);
				} else {
					if (bo.mesh) applySouthTowardParent(bo.mesh, body.position, parentPos);
					if (bo.model) applySouthTowardParent(bo.model, body.position, parentPos);
				}
			}
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

	oorState.satellites = ctx.refresher?.satelliteCoverage(jd) ?? { kind: 'covered' };
	updateOutOfRangeToast(oorState);

	// Lock focus onto the focused body's new position unless an animation is
	// driving it. Also refresh body-relative camera target so the fly
	// destination tracks the moving body.
	let reanchorId: string | null = null;
	if (focusedBody && oorState.focusedOutOfRange) {
		// Focused body has no data this frame — track the nearest in-range ancestor
		// so the camera follows it instead of freezing in world space. The focus
		// (and its "no data at this time" toast) stays on the original body; the
		// renderer pans the camera onto the anchor.
		const anchor = focusAncestors.find((a) => a.bo && !a.bo.outOfRange);
		if (anchor) {
			reanchorId = anchor.id;
			const p = positionMap.get(anchor.id) ?? anchor.oldPos;
			const elapsed = performance.now() - focus.focusStartTime;
			const animating = elapsed < focus.focusDurationMs;
			if (animating) {
				// A pan onto the anchor is running: keep its look target on the anchor.
				focus.focusTargetWorld[0] = p[0];
				focus.focusTargetWorld[1] = p[1];
				focus.focusTargetWorld[2] = p[2];
				const camOff = focus.camTargetOffset;
				if (camOff && focus.camTargetWorld) {
					focus.camTargetWorld[0] = p[0] + camOff[0];
					focus.camTargetWorld[1] = p[1] + camOff[1];
					focus.camTargetWorld[2] = p[2] + camOff[2];
				}
			} else {
				// Idle: shift the camera frame by the anchor's displacement so it keeps
				// tracking — beside the anchor before the pan, centered on it after.
				const dx = p[0] - anchor.oldPos[0];
				const dy = p[1] - anchor.oldPos[1];
				const dz = p[2] - anchor.oldPos[2];
				focus.focusTruePos[0] += dx;
				focus.focusTruePos[1] += dy;
				focus.focusTruePos[2] += dz;
				focus.focusTargetWorld[0] = focus.focusTruePos[0];
				focus.focusTargetWorld[1] = focus.focusTruePos[1];
				focus.focusTargetWorld[2] = focus.focusTruePos[2];
			}
		}
	} else if (focusedBody) {
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
		// Arc-orbit only: pin the arc's start point to the body too, so the arc
		// center stays equidistant from both ends and the body stays framed.
		const camOrigOff = focus.camOriginOffset;
		if (camOrigOff && focus.camOriginWorld) {
			focus.camOriginWorld[0] = p[0] + camOrigOff[0];
			focus.camOriginWorld[1] = p[1] + camOrigOff[1];
			focus.camOriginWorld[2] = p[2] + camOrigOff[2];
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

	return { focusedOutOfRange: oorState.focusedOutOfRange, reanchorId };
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
