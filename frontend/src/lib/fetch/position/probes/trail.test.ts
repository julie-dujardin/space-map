import { describe, it, expect } from 'vitest';
import { deriveProbeTrailParams, extendProbeTrailBuffer, frameFitPreference } from './trail';
import { TrailBuffer } from '$lib/fetch/position/trail-buffer';
import type { OrbitalElements } from '$lib/types/objects';

type Vec3 = [number, number, number];

/**
 * A probe trail samples in one fixed frame (`currentParentKey`). When the probe
 * appears in overlapping zones at the same jd (a flyby probe is in both the
 * interplanetary zone and the planet zone), the trail must resolve in its own
 * frame — otherwise the planet-zone samples are gated out and the encounter is
 * bridged with a straight line.
 */
describe('frameFitPreference', () => {
	it('a heliocentric trail prefers the Sun fit over an overlapping planet zone', () => {
		const pref = frameFitPreference('naif-10');
		expect(pref(10)).toBe(true); // interplanetary (Sun) — this trail's frame
		expect(pref(599)).toBe(false); // Jupiter zone the flyby probe also lives in
	});

	it('a planet-frame trail prefers its own planet fit', () => {
		const pref = frameFitPreference('naif-599');
		expect(pref(599)).toBe(true);
		expect(pref(10)).toBe(false);
	});

	it('an override frame (moon) matches no zone fit center, falling back to default order', () => {
		const pref = frameFitPreference('naif-901');
		expect(pref(699)).toBe(false); // Saturn zone fit center ≠ the moon override
		expect(pref(901)).toBe(true);
	});
});

/**
 * stepDays and epsilonScene are frame-dependent: a cross-zone parent flip must
 * re-derive them against the new primary, or a heliocentric-cruise buffer
 * (stepDays of days, epsilon of thousands of km — or Infinity from a boot where
 * elements hadn't resolved) walks a planet-frame encounter in segments several
 * planet radii long.
 */
describe('deriveProbeTrailParams', () => {
	const elems = (over: Partial<OrbitalElements>): OrbitalElements => ({
		a: 1,
		e: 0,
		i: 0,
		om: 0,
		w: 0,
		ma: 0,
		n: 1,
		epoch: 0,
		equatorial: false,
		...over
	});

	it('spreads the budget over one period and scales epsilon to periapsis', () => {
		const { stepDays, epsilonScene, spanDays } = deriveProbeTrailParams(
			elems({ a: 2, e: 0.5, n: 0.5 }),
			365,
			512
		);
		expect(stepDays).toBeCloseTo(720 / 512);
		expect(epsilonScene).toBeCloseTo(2 * 0.5 * 10 * 0.0001); // q=a(1−e)=1 AU
		expect(spanDays).toBeCloseTo(720); // one period — don't retrace loops
	});

	it('leaves hyperbolic fits (n ≤ 0) uncapped in span with a finite epsilon', () => {
		const { stepDays, epsilonScene, spanDays } = deriveProbeTrailParams(
			elems({ a: -3, e: 1.5, n: 0 }),
			12.9,
			512
		);
		expect(stepDays).toBeCloseTo(12.9 / 512);
		// q = a(1−e) = (−3)(−0.5) = 1.5 AU > 0 — flybys stay adaptive.
		expect(epsilonScene).toBeCloseTo(1.5 * 10 * 0.0001);
		// No loop to retrace — coverage / the parent gate bound the walk, so the
		// encounter trail isn't cut to one chunk window.
		expect(spanDays).toBe(Infinity);
	});

	it('degrades to uniform sampling when elements are unavailable', () => {
		const { stepDays, epsilonScene, spanDays } = deriveProbeTrailParams(null, 365, 512);
		expect(stepDays).toBeCloseTo(365 / 512);
		expect(epsilonScene).toBe(Infinity);
		expect(spanDays).toBeCloseTo(365); // uniform path spans its window
	});

	it('never returns a non-positive step', () => {
		const { stepDays } = deriveProbeTrailParams(null, 0, 512);
		expect(stepDays).toBe(1);
	});
});

describe('TrailBuffer.reconfigure', () => {
	it('swaps sampling params without touching stored samples', () => {
		const buf = new TrailBuffer(8, 1, Infinity);
		buf.append(5, 1, 2, 3);
		buf.reconfigure(0.25, 0.001, Infinity);
		expect(buf.stepDays).toBe(0.25);
		expect(buf.epsilonScene).toBe(0.001);
		expect(buf.spanDays).toBe(Infinity);
		expect(buf.count).toBe(1);
		expect(buf.newestJd).toBe(5);
	});

	it('keeps the previous step when handed a degenerate value', () => {
		const buf = new TrailBuffer(8, 1, Infinity);
		buf.reconfigure(NaN, 0.001);
		expect(buf.stepDays).toBe(1);
		buf.reconfigure(0, 0.002);
		expect(buf.stepDays).toBe(1);
		expect(buf.spanDays).toBe(8); // defaults back to stepDays × capacity
	});
});

/**
 * The live-play appender only ever adds the current frame's position, so a fast
 * periapsis pass jumps a large arc per frame and draws one long facet.
 * `extendProbeTrailBuffer` fills that gap with the same chord-error subdivision
 * as the back-fill: dense across curvature, sparse across straight arcs.
 */
describe('extendProbeTrailBuffer', () => {
	const R = 100;
	const omega = 0.5; // rad per jd — a full curved arc across the gap
	const circle = (t: number): Vec3 => [R * Math.cos(omega * t), R * Math.sin(omega * t), 0];

	it('subdivides a curved gap into many samples', () => {
		const buf = new TrailBuffer(512, 1, 0.5); // ε=0.5 world units → ~0.2 rad facets
		buf.append(0, ...circle(0));
		extendProbeTrailBuffer(buf, circle, 0, circle(0), 10);
		// One append per frame would give count 2; the arc needs far more.
		expect(buf.count).toBeGreaterThan(15);
		expect(buf.count).toBeLessThanOrEqual(512);
		expect(buf.newestJd).toBeCloseTo(10, 1); // reaches the head within one minStep
	});

	it('leaves a straight gap sparse (chord error stays zero)', () => {
		const line = (t: number): Vec3 => [t, 0, 0];
		const buf = new TrailBuffer(512, 1, 0.5);
		buf.append(0, ...line(0));
		extendProbeTrailBuffer(buf, line, 0, line(0), 10);
		expect(buf.count).toBeLessThanOrEqual(3); // seed + a single max-length step
	});

	it('is a no-op when adaptive sampling is disabled (ε = Infinity)', () => {
		const buf = new TrailBuffer(512, 1); // defaults ε to Infinity
		buf.append(0, ...circle(0));
		extendProbeTrailBuffer(buf, circle, 0, circle(0), 10);
		expect(buf.count).toBe(1);
	});

	it('stops when the sampler hits a coverage gap', () => {
		const gated = (t: number): Vec3 | null => (t > 3 ? null : circle(t));
		const buf = new TrailBuffer(512, 1, 0.5);
		buf.append(0, ...circle(0));
		extendProbeTrailBuffer(buf, gated, 0, circle(0), 10);
		expect(buf.newestJd).toBeLessThanOrEqual(3);
	});
});
