import { describe, it, expect } from 'vitest';
import { extendProbeTrailBuffer, frameFitPreference } from './trail';
import { TrailBuffer } from '$lib/fetch/position/trail-buffer';

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
