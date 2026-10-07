import { Quaternion, type Vector3 } from 'three';
import {
	isMajorBody,
	isSurfaceFeature,
	type PositionedBody,
	type Unplaced
} from '$lib/types/objects';
import { seatFeatureBody } from './feature-seat';
import { kmToScene } from '$lib/math/units';
import {
	applyOrientation,
	applyPointing,
	applySouthTowardParent,
	applyUpVector,
	type PointingSpec
} from '$lib/math/orientation';
import { isModelBearing } from '$lib/scene/objects/body/model';
import { EARTH_ID, SSB_ID, SUN_ID } from '$lib/constants';
import { classifyLagrange } from '$lib/math/orbit/lagrange';
import { elementsOffset, existsAt } from '$lib/math/orbit/offset';
import { OrbitalSource } from '$lib/fetch/position/format';
import { isLandedAt, probePositionKm } from '$lib/fetch/position/probes/propagate';
import { resolveProbePrimary } from '$lib/fetch/position/probes/primary';
import {
	buildParentGatedSampler,
	deriveProbeTrailParams,
	extendProbeTrailBuffer,
	populateProbeTrailBuffer
} from '$lib/fetch/position/probes/trail';
import { probeOsculatingElements } from '$lib/fetch/position/probes/elements';
import { planRideMarkers } from '$lib/fetch/position/probes/passenger';
import { ADAPTIVE_MIN_STEP_FACTOR } from '$lib/fetch/position/trail-buffer';
import type { BodyObjects } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { Vec3 } from '$lib/scene/animation/math';
import { emptyGroup, type OutOfRangeGroup } from '$lib/scene/out-of-range-notice';
import { renderLandedProbe } from './landed-probe';
import { setSpacecraftGlyph } from '$lib/scene/label/factory';
import { setLabelAnnotation } from '$lib/scene/label/annotations';
import { host } from '$lib/host';
import type { PositionDiagnostics } from './diagnostics';
import { SSB_POSITION, setOrbitCenter, setPlaced, setTrailAnchor, setUnplaced } from './placement';

/** Module-scope scratch for adaptive trail chord-error sampling. JS is single-
 *  threaded and the buffer is consumed within one probe iteration, so reusing
 *  one allocation across all probes per frame is safe and avoids GC churn. */
const newestPosScratch: [number, number, number] = [0, 0, 0];

/** Scratch for the focused probe's attitude quaternion (one body per frame). */
const attitudeQuat = new Quaternion();

/** A hidden probe or minor body moves on every `HIDDEN_STRIDE`th frame only;
 *  nothing on screen reads its position in between. */
const HIDDEN_STRIDE = 4;
let nextStaggerSlot = 0;

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

/**
 * Settles where a body is at a date. The frame loop and every other reader go
 * through `place`, so one set of rules decides what has a place.
 *
 * A place is settled into the scene. While the scene stays at the date of the
 * last pass, a reader gets the place for that date: one for the date it asks
 * for would move the body in a scene that shows another date.
 */
export class Placer {
	/** Placed on every frame, hidden or not. */
	focusedId: string | undefined;
	/** Major bodies the ephemeris does not reach at the pass date. */
	noData: OutOfRangeGroup = emptyGroup();
	private passJd = NaN;
	private frame: number | undefined;
	/** Bodies settled for `passJd`. */
	private readonly settled = new Set<string>();
	/** Bodies being settled now, to stop a parent cycle. */
	private readonly settling = new Set<string>();
	private ride = planRideMarkers([], undefined, () => undefined);
	private rideJd = NaN;
	private rideFocus: string | undefined;

	constructor(
		private readonly ctx: ContextManager,
		private readonly bodyObjects: Map<string, BodyObjects>,
		private readonly diagnostics: PositionDiagnostics,
		/** True while the scene stays at the date of the last pass. */
		private readonly held: () => boolean = () => false
	) {}

	/** Open a frame pass at `jd`. `frame` absent: no body is skipped. */
	begin(jd: number, focusedId: string | undefined, frame: number | undefined): void {
		this.passJd = jd;
		this.focusedId = focusedId;
		this.frame = frame;
		this.settled.clear();
		this.noData = emptyGroup();
	}

	/** Place of the body `id` at `jd`. Null when it has none or is not loaded. */
	at(id: string, jd: number): Vec3 | null {
		if (id === SSB_ID) return SSB_POSITION;
		const body = this.ctx.getBody(id) ?? this.bodyObjects.get(id)?.body;
		return body ? this.place(body, jd) : null;
	}

	/** Frame-loop entry. A hidden probe or minor body keeps its last place on
	 *  most frames: a reader that needs it calls `place`. */
	placeInPass(body: PositionedBody): void {
		const d = body.data;
		const bo = this.bodyObjects.get(d.id);
		if (
			bo &&
			this.frame !== undefined &&
			d.id !== this.focusedId &&
			!bo.root.visible &&
			!bo.trail?.visible &&
			(d.orbitalSource === OrbitalSource.SPICE_PROBE || !isMajorBody(d.objectType))
		) {
			bo.staggerSlot ??= nextStaggerSlot++ % HIDDEN_STRIDE;
			if (this.frame % HIDDEN_STRIDE !== bo.staggerSlot) return;
		}
		this.place(body, this.passJd);
	}

	/** Settle `body` for `jd` and return its place. Null when it has none. */
	place(body: PositionedBody, jd: number): Vec3 | null {
		if (jd !== this.passJd && this.held()) jd = this.passJd;
		const id = body.data.id;
		if (jd === this.passJd && this.settled.has(id)) return body.position;
		if (this.settling.has(id)) {
			this.diagnostics.warnOnce('parent-cycle', id, () => `place[${id}]: parent chain loops`);
			return null;
		}
		this.settling.add(id);
		const pos = isSurfaceFeature(body) ? this.seatFeature(body, jd) : this.settle(body, jd);
		this.settling.delete(id);
		if (jd === this.passJd) this.settled.add(id);
		return pos;
	}

	/** Why a body has no place when the body `aboveId` it is placed from has
	 *  none. A load passes down: the body comes back with the data. */
	private under(aboveId: string): Unplaced {
		const above = this.ctx.getBody(aboveId) ?? this.bodyObjects.get(aboveId)?.body;
		return above?.unplaced === 'loading' ? 'loading' : 'parent';
	}

	/** A surface feature sits on its host. */
	private seatFeature(body: PositionedBody, jd: number): Vec3 | null {
		const hostId = body.featureAnchor!.hostId;
		const host = this.ctx.getBody(hostId);
		const hostPos = host && this.place(host, jd);
		if (!host || !hostPos) return setUnplaced(body, this.under(hostId));
		return seatFeatureBody(body, host, hostPos, this.bodyObjects.get(hostId), jd);
	}

	private rideAt(jd: number): ReturnType<typeof planRideMarkers> {
		if (jd !== this.rideJd || this.focusedId !== this.rideFocus) {
			this.rideJd = jd;
			this.rideFocus = this.focusedId;
			this.ride = planRideMarkers(
				this.ctx.probeStore?.ridesAt(jd) ?? [],
				this.focusedId,
				(id) => this.ctx.getBody(id)?.data.name
			);
		}
		return this.ride;
	}

	/** Offset from `parentPos` of a body the ephemeris does not reach, from its
	 *  catalogue row. The row can hang off another parent than the ephemeris does. */
	private rowOffset(body: PositionedBody, parentPos: Readonly<Vec3>, jd: number): Vec3 | null {
		const row = this.ctx.bodies.elementRow(body);
		const rowParentPos = row && this.at(row.parentId, jd);
		if (!rowParentPos) return null;
		const offset = elementsOffset(row, jd);
		if (typeof offset === 'string') return null;
		return [
			rowParentPos[0] - parentPos[0] + offset[0],
			rowParentPos[1] - parentPos[1] + offset[1],
			rowParentPos[2] - parentPos[2] + offset[2]
		];
	}

	private settle(body: PositionedBody, jd: number): Vec3 | null {
		const { ctx, diagnostics } = this;
		const d = body.data;
		const bo = this.bodyObjects.get(d.id);
		if (d.pageOnly) return setUnplaced(body, 'never');
		if (d.orbitalSource === OrbitalSource.SPICE_PROBE) return this.settleProbe(body, bo, jd);
		const parentPos = this.at(d.parentId, jd);
		if (!parentPos) {
			const why = this.under(d.parentId);
			if (why === 'parent') {
				diagnostics.warnOnce(
					'missing-parent',
					d.id,
					() => `place[${d.id}]: parent ${d.parentId} has no place`
				);
			}
			return setUnplaced(body, why);
		}
		diagnostics.clear('missing-parent', d.id);
		let offset: Vec3 | Unplaced;
		if (ctx.chebStore?.has(d.id)) {
			// A probe target's ephemeris spans its mission only: its element row
			// carries it the rest of the time. A body with no row has no place
			// then: an extrapolated planet or moon would break eclipse geometry.
			offset = !existsAt(d, jd)
				? 'not-yet'
				: (ctx.chebStore.positionScene(d.id, jd) ??
					this.rowOffset(body, parentPos, jd) ??
					this.chebMiss(d.id, jd));
		} else {
			offset = elementsOffset(d, jd);
		}
		if (typeof offset === 'string') return setUnplaced(body, offset);
		return this.finish(
			body,
			bo,
			parentPos[0] + offset[0],
			parentPos[1] + offset[1],
			parentPos[2] + offset[2],
			parentPos,
			jd
		);
	}

	/** Why the ephemeris has nothing for `id` at `jd`: the chunk for the date is
	 *  on its way, or the ephemeris does not reach the date. */
	private chebMiss(id: string, jd: number): Unplaced {
		const store = this.ctx.chebStore!;
		if (store.isLoading(id, jd)) return 'loading';
		const coverage = store.zoneCoverage(id);
		const outside = coverage !== null && (jd < coverage.start || jd > coverage.end);
		if (outside && jd === this.passJd) {
			this.noData.count++;
			if (coverage.start < this.noData.earliestStart) this.noData.earliestStart = coverage.start;
			if (coverage.end > this.noData.latestEnd) this.noData.latestEnd = coverage.end;
		}
		this.diagnostics.warnOnce('cheb-null', id, () => {
			const cov = coverage
				? `[${coverage.start.toFixed(1)},${coverage.end.toFixed(1)}]`
				: 'unknown';
			return `chebStore.positionScene[${id}] returned null at jd=${jd.toFixed(3)} (coverage=${cov})`;
		});
		return 'no-data';
	}

	/** Write the place, the orbit centre and the attitude of a body. */
	private finish(
		body: PositionedBody,
		bo: BodyObjects | undefined,
		x: number,
		y: number,
		z: number,
		parentPos: Readonly<Vec3>,
		jd: number
	): Vec3 | null {
		const d = body.data;
		const pos = setPlaced(body, x, y, z);
		if (!pos) {
			this.diagnostics.warnOnce(
				'non-finite',
				d.id,
				() => `place[${d.id}] non-finite: pos=[${x},${y},${z}] parentId=${d.parentId}`
			);
			return null;
		}
		const centerId = body.orbitCenterId;
		if (centerId !== undefined) {
			setOrbitCenter(body, centerId === d.parentId ? parentPos : this.at(centerId, jd));
		}
		if (body.trailAnchorId !== undefined) {
			const anchor = this.at(body.trailAnchorId, jd);
			if (anchor) setTrailAnchor(body, anchor);
		}

		if (!bo) return pos;
		if (bo.trail && body.orbitCenter) {
			const oc = bo.trail.userData.orbitCenter as Vector3 | undefined;
			if (oc) oc.set(body.orbitCenter[0], body.orbitCenter[1], body.orbitCenter[2]);
		}
		if (body.orientation && (bo.mesh || bo.model)) {
			if (bo.mesh) applyOrientation(bo.mesh, body.orientation, jd, body.nutPrec);
			// Natural-body shape model shares the sphere's IAU spin. Neither its
			// mount nor the overlay carries rotation, so writing the local
			// quaternion is enough. The label anchor co-rotates so surface
			// features stay pinned to the model.
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
					const velocity = needsVelocity(spec) ? estimateVelocity(d.id, jd, pos) : undefined;
					const pctx = {
						bodyPos: pos,
						parentPos,
						sunPos: this.at(SUN_ID, jd) ?? undefined,
						velocity
					};
					if (bo.mesh) applyPointing(bo.mesh, spec, pctx);
					if (bo.model) applyPointing(bo.model, spec, pctx);
				} else {
					if (bo.mesh) applySouthTowardParent(bo.mesh, pos, parentPos);
					if (bo.model) applySouthTowardParent(bo.model, pos, parentPos);
				}
			}
		}
		// Rings inherit the planet's pole orientation (geometry pre-rotated so
		// local +Y is the pole). Re-apply each frame so nutation/precession/spin
		// stay in sync with the planet.
		if (body.orientation) {
			for (const ring of bo.rings) {
				applyOrientation(ring.mesh, body.orientation, jd, body.nutPrec);
			}
		}
		return pos;
	}

	/** A probe: its fit centre comes from the zone that covers `jd`, so the
	 *  parent can change between two dates. */
	private settleProbe(body: PositionedBody, bo: BodyObjects | undefined, jd: number): Vec3 | null {
		const { ctx, bodyObjects, diagnostics } = this;
		const d = body.data;
		const ride = this.rideAt(jd);
		if (bo) {
			// The other half of a carried pair: the marker of the carrier is both of them.
			bo.carried = ride.hidden.has(d.id);
			const carrier = ride.credits.get(d.id);
			setLabelAnnotation(
				bo,
				'carrier',
				carrier ? host().messages.carried_by_scene_label({ carrier }) : null
			);
		}
		// When zoomed into a planet, prefer its zone over interplanetary so flyby
		// probes take the planet-relative fit and flip parentId to the planet.
		const activeSysId = ctx.visibility.activeSystemId;
		const zonePref = activeSysId
			? (fitCenterNaif: number) => ctx.bodies.isInSystem(`naif-${fitCenterNaif}`, activeSysId)
			: undefined;
		// Probes dispatch per sub-chunk inside the store. Fit center is the
		// zone's `fit_center_naif_id` — NOT d.parentId (which lags by a frame
		// at cross-zone transitions). Re-resolve per frame, then flip parentId
		// so trail geometry and trail-anchor writes follow the new parent.
		const located = ctx.probeStore?.probeWithCenter(d.id, jd, zonePref) ?? null;
		if (!located) {
			// A chunk on its way can hold the craft.
			if (ctx.probeStore?.loadingAt(jd)) return setUnplaced(body, 'loading');
			setUnplaced(body, 'no-data');
			diagnostics.warnOnce('probe-unavailable', d.id, () => {
				const reason = !ctx.probeStore
					? 'no ProbeStore'
					: 'no zone has both a loaded chunk and a sub-chunk covering this jd';
				return `probe ${d.id} (${d.name ?? 'unnamed'}): hidden — ${reason}`;
			});
			return null;
		}
		// Landed branch: place at lat/lng on the landing body's surface,
		// applying its IAU orientation. Skip the flying-fit path entirely.
		const probeLanded = located.probe.landed;
		if (probeLanded && isLandedAt(located.probe, jd)) {
			// Captured before `renderLandedProbe` re-parents the craft.
			const flyingFrameId = d.parentId;
			const landedRender = renderLandedProbe(
				d,
				located.probe,
				probeLanded,
				jd,
				(id) => this.at(id, jd),
				ctx,
				bodyObjects
			);
			if (!landedRender) {
				return setUnplaced(body, this.under(`naif-${probeLanded.bodyNaifId}`));
			}
			diagnostics.clear('probe-unavailable', d.id);
			// A craft that lands on a body other than the one its flying fits
			// were against — Huygens fitted on Saturn, standing on Titan —
			// leaves a buffer full of offsets from the wrong origin. Drawn
			// against the new one they rule a line from the landing site out
			// to the old frame, so the descent trail ends at touchdown.
			if (flyingFrameId !== d.parentId) body.trailBuffer?.clear();
			if (bo) {
				const crashed = probeLanded.isDestroyed;
				if (!bo.isLanded) {
					setSpacecraftGlyph(bo.labelHalo, 'landed');
					bo.isLanded = true;
				}
				bo.isCrashed = crashed;
				// A crash site has no intact craft to stand on it.
				if (bo.model) bo.model.visible = !crashed;
			}
			const pos = setPlaced(body, landedRender.x, landedRender.y, landedRender.z);
			if (!pos) return null;
			body.orbitCenterId = d.parentId;
			setOrbitCenter(body, landedRender.parentPos);
			// Stand the lander on the terrain slope (seat facet's normal); radial
			// nadir until the seat resolves. Camera-north stays radial either way
			// (bodyNorthVector), only the model tilts.
			const up = landedRender.up;
			if (bo?.mesh) {
				if (up) applyUpVector(bo.mesh, up);
				else applySouthTowardParent(bo.mesh, pos, landedRender.parentPos);
			}
			if (bo?.model) {
				if (up) applyUpVector(bo.model, up);
				else applySouthTowardParent(bo.model, pos, landedRender.parentPos);
			}
			return pos;
		}
		// Resolve the probe's stamped primary (Moon for lunar orbiters,
		// Ryugu for Hayabusa2, …) or the zone center. Sub-chunks are fit
		// against THAT body, so the propagator's mu must match; a primary
		// that can't be placed this frame means hide, not fall back.
		const primary = resolveProbePrimary(
			located.probe,
			jd,
			located.fitCenterNaifId,
			ctx.chebStore ?? null,
			(id) => this.at(id, jd) !== null
		);
		if (!primary) {
			const center = located.probe.fitCenter?.id;
			setUnplaced(body, center ? this.under(center) : 'parent');
			diagnostics.warnOnce(
				'probe-unavailable',
				d.id,
				() =>
					`probe ${d.id} (${d.name ?? 'unnamed'}): hidden — stamped fit center ` +
					'is not placeable this frame'
			);
			return null;
		}
		const probeParentKey = primary.id;
		const primaryMu = primary.muKm3S2;
		const probeOffsetKm = probePositionKm(located.probe, jd, primaryMu);
		if (!probeOffsetKm) {
			setUnplaced(body, 'no-data');
			diagnostics.warnOnce(
				'probe-unavailable',
				d.id,
				() =>
					`probe ${d.id} (${d.name ?? 'unnamed'}): hidden — sub-chunk evaluation returned ` +
					'null (uncoverable, non-finite fit, or missing mu for kepler_pure)'
			);
			return null;
		}
		diagnostics.clear('probe-unavailable', d.id);
		if (bo?.isLanded) {
			setSpacecraftGlyph(bo.labelHalo, 'flying');
			bo.isLanded = false;
			if (bo.isCrashed) {
				bo.isCrashed = false;
				if (bo.model) bo.model.visible = true;
				if (!bo.noPhysical) setLabelAnnotation(bo, 'missing', null);
			}
		}
		// Sun–Earth L1/L2 is decided from the live geometry, so a probe gets
		// its halo trail when it arrives and loses it when it leaves. The
		// envelope is wide enough that a halo never wanders across the edge.
		const earthPos = this.at(EARTH_ID, jd);
		const sunPos = this.at(SUN_ID, jd);
		const lagrangeTrail =
			probeParentKey === EARTH_ID &&
			earthPos !== null &&
			sunPos !== null &&
			classifyLagrange(
				[kmToScene(probeOffsetKm[0]), kmToScene(probeOffsetKm[2]), -kmToScene(probeOffsetKm[1])],
				[sunPos[0] - earthPos[0], sunPos[1] - earthPos[1], sunPos[2] - earthPos[2]]
			) !== null;
		const lagrangeChanged = lagrangeTrail !== (body.lagrangeTrail ?? false);
		body.lagrangeTrail = lagrangeTrail;
		// Reseed the trail buffer (when present) before flipping parentId,
		// so the back-population samples against the OLD parent's frame are
		// dropped and the new frame starts fresh. Sampling params must be
		// re-derived in the NEW frame first: reusing cruise-scale stepDays/
		// epsilon for a planet-frame flyby walks the encounter in segments
		// several Jupiter radii long (visibly spiky trail), and the reverse
		// truncates a heliocentric trail to one chunk window. Skip on
		// first-ever resolve (initial parentId was set by processProbes
		// against the same parent) — only the live mid-play flip needs a clear.
		// A Lagrange arrival or departure reseeds the same way: the halo
		// span and the osculating span are different walks.
		const probeParentChanged = d.parentId !== probeParentKey;
		if ((probeParentChanged || lagrangeChanged) && body.trailBuffer && ctx.probeStore) {
			const buf = body.trailBuffer;
			buf.clear();
			buf.needsPopulate = false;
			const freshElements = probeOsculatingElements(located.probe, jd, primaryMu);
			const params = deriveProbeTrailParams(
				freshElements,
				d.validityEnd - d.validityStart,
				buf.capacity,
				lagrangeTrail
			);
			buf.reconfigure(params.stepDays, params.epsilonScene, params.spanDays);
			populateProbeTrailBuffer(
				buf,
				ctx.probeStore,
				ctx.chebStore ?? null,
				d.id,
				probeParentKey,
				jd
			);
		}
		if (probeParentChanged) d.parentId = probeParentKey;
		// The fit center must be placed first: without it the probe would land
		// at the scene origin, which reads as a jump to the barycentre.
		const probeParentPos = this.at(probeParentKey, jd);
		if (!probeParentPos) {
			setUnplaced(body, this.under(probeParentKey));
			diagnostics.warnOnce(
				'probe-unavailable',
				d.id,
				() =>
					`probe ${d.id} (${d.name ?? 'unnamed'}): hidden — fit center ${probeParentKey} ` +
					'has no position this frame'
			);
			return null;
		}
		const parentPos = probeParentPos;
		const probeOffsetX = kmToScene(probeOffsetKm[0]);
		const probeOffsetY = kmToScene(probeOffsetKm[2]);
		const probeOffsetZ = -kmToScene(probeOffsetKm[1]);
		const x = parentPos[0] + probeOffsetX;
		const y = parentPos[1] + probeOffsetY;
		const z = parentPos[2] + probeOffsetZ;
		// Trail-buffer maintenance. A backwards jump or a gap > one full span
		// invalidates the samples — reseed via back-populate. Otherwise extend
		// forward from the newest sample with the same chord-error subdivision as
		// the back-fill, so a fast periapsis pass (a large arc per frame at high
		// time-speed) densifies instead of drawing one long facet per frame.
		const tb = body.trailBuffer;
		// The load-time back-fill is owed until the trail first shows.
		if (tb?.needsPopulate && bo?.trail?.visible && ctx.probeStore) {
			tb.needsPopulate = false;
			tb.clear();
			populateProbeTrailBuffer(tb, ctx.probeStore, ctx.chebStore ?? null, d.id, probeParentKey, jd);
		}
		if (tb) {
			const last = tb.newestJd;
			const dt = jd - last;
			const span = tb.stepDays * tb.capacity;
			// A backward jump or a gap wider than one buffered period invalidates
			// the samples. A tight orbit trips this every frame above ~day/s, so a
			// full per-period reseed would run continuously for every probe.
			const discontinuity = isFinite(last) && (dt < 0 || dt > span);
			if (discontinuity && d.id === this.focusedId && ctx.probeStore) {
				// Focused probe only: rebuild one accurate osculating period ending on
				// the body so a close-up stays smooth even when a frame skips many
				// orbits. Re-derive params — the orbit may have changed across the jump.
				tb.clear();
				const jumpElements = probeOsculatingElements(located.probe, jd, primaryMu);
				const params = deriveProbeTrailParams(
					jumpElements,
					d.validityEnd - d.validityStart,
					tb.capacity,
					lagrangeTrail
				);
				tb.reconfigure(params.stepDays, params.epsilonScene, params.spanDays);
				populateProbeTrailBuffer(
					tb,
					ctx.probeStore,
					ctx.chebStore ?? null,
					d.id,
					probeParentKey,
					jd
				);
			} else if (discontinuity) {
				// Unfocused: the orbit is sub-pixel at the speeds that trip this, so the
				// per-period reseed is wasted work. Drop the stale samples (an orbit-wide
				// facet would otherwise spike) and restart on the body.
				tb.clear();
				tb.append(jd, probeOffsetX, probeOffsetY, probeOffsetZ);
			} else if (!isFinite(last)) {
				tb.append(jd, probeOffsetX, probeOffsetY, probeOffsetZ);
			} else if (isFinite(tb.epsilonScene)) {
				const minStep = tb.stepDays * ADAPTIVE_MIN_STEP_FACTOR;
				if (dt >= minStep && ctx.probeStore && tb.readNewestPos(newestPosScratch)) {
					extendProbeTrailBuffer(
						tb,
						buildParentGatedSampler(ctx.probeStore, ctx.chebStore ?? null, d.id, probeParentKey),
						last,
						[newestPosScratch[0], newestPosScratch[1], newestPosScratch[2]],
						jd
					);
				}
			} else if (dt >= tb.stepDays) {
				tb.append(jd, probeOffsetX, probeOffsetY, probeOffsetZ);
			}
		}
		body.orbitCenterId = d.parentId;
		return this.finish(body, bo, x, y, z, parentPos, jd);
	}
}
