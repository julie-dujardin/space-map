import { describe, expect, it } from 'vitest';
import { AU_KM } from '$lib/math/units';
import type { TravelBody } from './body';
import { GM_SUN_KM3_S2 } from './constants';
import { buildSubwayMap, stationId, type SubwayBodies, type SubwayBody } from './subway';
import { EARTH, EUROPA, IO, JUPITER, MARS, MOON } from './test-fixtures';

/** Published figures the map is checked against, km/s: LEO to a Mars
 *  transfer 3.6, TLI 3.1, lunar orbit insertion 0.8–0.9, Mars orbit insertion
 *  into a low circular orbit about 2.1. */

function body(
	travel: TravelBody,
	primaryId: string,
	orbitRadiusKm: number,
	ground = true
): SubwayBody {
	return { id: travel.id, mu: travel.mu, primaryId, orbitRadiusKm, travel, ground };
}

const SUN: SubwayBody = {
	id: 'naif-10',
	mu: GM_SUN_KM3_S2,
	primaryId: null,
	orbitRadiusKm: 0,
	travel: {
		id: 'naif-10',
		mu: GM_SUN_KM3_S2,
		muEstimated: false,
		radiusKm: 695700,
		elements: EARTH.elements,
		hasAtmosphere: true
	},
	ground: false
};

/** Geostationary radius, km. */
const GEO_KM = 42164;

/** Mars, given an atmosphere thick enough to brake in. */
const MARS_WITH_AIR: TravelBody = {
	...MARS,
	surfacePressureBar: 0.006,
	hasAtmosphere: true,
	aeroPressurePa: 636,
	aeroScaleHeightKm: 11
};

const EARTH_WITH_AIR: TravelBody = {
	...EARTH,
	surfacePressureBar: 1,
	hasAtmosphere: true,
	aeroPressurePa: 101325,
	aeroScaleHeightKm: 8.5
};

function system(): SubwayBodies {
	return new Map(
		[
			SUN,
			{ ...body(EARTH_WITH_AIR, 'naif-10', EARTH.elements.a * AU_KM), synchronousRadiusKm: GEO_KM },
			body(MARS_WITH_AIR, 'naif-10', MARS.elements.a * AU_KM),
			body(MOON, 'naif-399', MOON.elements.a * AU_KM),
			body(JUPITER, 'naif-10', JUPITER.elements.a * AU_KM, false),
			body(EUROPA, 'naif-599', EUROPA.elements.a * AU_KM),
			body(IO, 'naif-599', IO.elements.a * AU_KM)
		].map((b) => [b.id, b])
	);
}

function edge(map: ReturnType<typeof buildSubwayMap>, from: string, to: string) {
	const found = map.edges.find((e) => e.from === from && e.to === to);
	if (!found) throw new Error(`no edge ${from} → ${to}`);
	return found;
}

function route(map: ReturnType<typeof buildSubwayMap>, targetId: string) {
	const found = map.routes.find((r) => r.targetId === targetId);
	if (!found) throw new Error(`no route to ${targetId}`);
	return found;
}

describe('buildSubwayMap', () => {
	it('prices Earth to Mars as launch, escape, the Hohmann extra, capture, landing', () => {
		const map = buildSubwayMap(system(), 'naif-399', ['naif-499']);
		const r = route(map, 'naif-499');
		expect(r.path).toEqual([
			stationId('surface', 'naif-399'),
			stationId('orbit', 'naif-399'),
			stationId('escape', 'naif-399'),
			stationId('transfer', 'naif-499'),
			stationId('escape', 'naif-499'),
			stationId('orbit', 'naif-499'),
			stationId('surface', 'naif-499')
		]);
		const ascent = edge(map, r.path[0], r.path[1]).dvKms;
		const escape = edge(map, r.path[1], r.path[2]).dvKms;
		const depart = edge(map, r.path[2], r.path[3]).dvKms;
		const arrive = edge(map, r.path[3], r.path[4]).dvKms;
		const circularize = edge(map, r.path[4], r.path[5]).dvKms;
		expect(ascent).toBeGreaterThan(9.2);
		expect(ascent).toBeLessThan(9.6);
		expect(escape).toBeGreaterThan(3.1);
		expect(escape).toBeLessThan(3.3);
		expect(escape + depart).toBeGreaterThan(3.5);
		expect(escape + depart).toBeLessThan(3.7);
		expect(arrive + circularize).toBeGreaterThan(2.0);
		expect(arrive + circularize).toBeLessThan(2.3);
		expect(r.orbitKms).toBeCloseTo(ascent + escape + depart + arrive + circularize, 9);
		expect(r.transferDays).toBeGreaterThan(250);
		expect(r.transferDays).toBeLessThan(270);
	});

	it('lets an atmosphere take the arrival and the landing', () => {
		const map = buildSubwayMap(system(), 'naif-399', ['naif-499']);
		const r = route(map, 'naif-499');
		expect(edge(map, stationId('transfer', 'naif-499'), stationId('escape', 'naif-499')).aero).toBe(
			true
		);
		expect(edge(map, stationId('orbit', 'naif-499'), stationId('surface', 'naif-499')).aero).toBe(
			true
		);
		expect(r.aeroOrbitKms).not.toBeNull();
		expect(r.aeroOrbitKms!).toBeLessThan(r.orbitKms);
		expect(r.aeroSurfaceKms!).toBeLessThan(r.surfaceKms!);
		// Airless: the escape edge at Earth carries no flag either way.
		expect(edge(map, stationId('orbit', 'naif-399'), stationId('escape', 'naif-399')).aero).toBe(
			false
		);
	});

	it('flies Earth to the Moon on a bound ellipse with no escape stop', () => {
		const map = buildSubwayMap(system(), 'naif-399', ['naif-301']);
		const r = route(map, 'naif-301');
		expect(r.path).toEqual([
			stationId('surface', 'naif-399'),
			stationId('orbit', 'naif-399'),
			stationId('transfer', 'naif-301'),
			stationId('escape', 'naif-301'),
			stationId('orbit', 'naif-301'),
			stationId('surface', 'naif-301')
		]);
		const tli = edge(map, r.path[1], r.path[2]).dvKms;
		const capture = edge(map, r.path[2], r.path[3]).dvKms + edge(map, r.path[3], r.path[4]).dvKms;
		expect(tli).toBeGreaterThan(3.0);
		expect(tli).toBeLessThan(3.2);
		expect(capture).toBeGreaterThan(0.7);
		expect(capture).toBeLessThan(0.95);
		expect(r.transferDays).toBeGreaterThan(4);
		expect(r.transferDays).toBeLessThan(6);
		expect(r.aeroOrbitKms).toBeNull();
	});

	it('brings the Moon back to Earth straight into low orbit, braked by the air', () => {
		const map = buildSubwayMap(system(), 'naif-301', ['naif-399']);
		const r = route(map, 'naif-399');
		expect(r.path).toEqual([
			stationId('surface', 'naif-301'),
			stationId('orbit', 'naif-301'),
			stationId('escape', 'naif-301'),
			stationId('transfer', 'naif-399'),
			stationId('orbit', 'naif-399'),
			stationId('surface', 'naif-399')
		]);
		const arrive = edge(map, r.path[3], r.path[4]);
		expect(arrive.dvKms).toBeGreaterThan(3.0);
		expect(arrive.dvKms).toBeLessThan(3.2);
		expect(arrive.aero).toBe(true);
		expect(r.aeroOrbitKms!).toBeLessThan(r.orbitKms - 2.5);
	});

	it('shares the Jupiter transfer between Jupiter and its moons', () => {
		const map = buildSubwayMap(system(), 'naif-399', ['naif-599', 'naif-502']);
		const jupiter = route(map, 'naif-599');
		const europa = route(map, 'naif-502');
		const transfer = stationId('transfer', 'naif-599');
		expect(jupiter.path).toContain(transfer);
		expect(europa.path).toContain(transfer);
		expect(europa.path).not.toContain(stationId('escape', 'naif-599'));
		// One trunk: the shared stops and edges appear once.
		expect(map.stations.filter((s) => s.id === transfer)).toHaveLength(1);
		expect(map.edges.filter((e) => e.to === transfer)).toHaveLength(1);
		// The coast through Jupiter's well is recorded, not priced.
		const arrive = edge(map, transfer, stationId('escape', 'naif-502'));
		expect(arrive.via).toEqual(['naif-599']);
		const capture =
			arrive.dvKms +
			edge(map, stationId('escape', 'naif-502'), stationId('orbit', 'naif-502')).dvKms;
		expect(capture).toBeGreaterThan(4.5);
		expect(capture).toBeLessThan(6.5);
		// No ground on a giant.
		expect(jupiter.surfaceKms).toBeNull();
		expect(map.stations.some((s) => s.id === stationId('surface', 'naif-599'))).toBe(false);
	});

	it('routes between two moons about their planet', () => {
		const map = buildSubwayMap(system(), 'naif-502', ['naif-501']);
		const r = route(map, 'naif-501');
		expect(r.path).toEqual([
			stationId('surface', 'naif-502'),
			stationId('orbit', 'naif-502'),
			stationId('escape', 'naif-502'),
			stationId('transfer', 'naif-501'),
			stationId('escape', 'naif-501'),
			stationId('orbit', 'naif-501'),
			stationId('surface', 'naif-501')
		]);
		expect(edge(map, r.path[2], r.path[3]).via).toEqual([]);
		expect(r.transferDays).toBeGreaterThan(1);
		expect(r.transferDays).toBeLessThan(3);
	});

	it('climbs out of Earth on the way from the Moon to Mars', () => {
		const map = buildSubwayMap(system(), 'naif-301', ['naif-499']);
		const r = route(map, 'naif-499');
		// Earth's escape is a stop of its own on the trunk, past the Moon's, and
		// the Sun's ends the line.
		expect(map.trunk).toEqual([
			stationId('surface', 'naif-301'),
			stationId('orbit', 'naif-301'),
			stationId('escape', 'naif-301'),
			stationId('escape', 'naif-399'),
			stationId('escape', 'naif-10')
		]);
		expect(r.path.slice(0, 5)).toEqual([
			...map.trunk.slice(0, 4),
			stationId('transfer', 'naif-499')
		]);
		expect(
			edge(map, stationId('escape', 'naif-399'), stationId('transfer', 'naif-499')).via
		).toEqual([]);
		// The two rungs together are what leaving used to cost in one step.
		const climb = edge(map, stationId('escape', 'naif-301'), stationId('escape', 'naif-399'));
		expect(climb.dvKms).toBeGreaterThan(0);
		// Cheaper to leave than Earth's own orbit is: the Moon is most of the way up the well.
		const fromEarth = route(buildSubwayMap(system(), 'naif-399', ['naif-499']), 'naif-499');
		expect(r.orbitKms).toBeLessThan(fromEarth.orbitKms);
	});

	it('skips the origin itself and anything off the tree', () => {
		const map = buildSubwayMap(system(), 'naif-399', ['naif-399', 'naif-1', 'naif-499']);
		expect(map.routes.filter((r) => r.kind === 'body').map((r) => r.targetId)).toEqual([
			'naif-499'
		]);
	});

	it('starts at low orbit when the origin has no ground', () => {
		const map = buildSubwayMap(system(), 'naif-599', ['naif-502']);
		const r = route(map, 'naif-502');
		expect(r.path[0]).toBe(stationId('orbit', 'naif-599'));
		expect(map.stations.some((s) => s.kind === 'surface' && s.bodyId === 'naif-599')).toBe(false);
	});

	it('is empty for an origin the map does not hold', () => {
		const map = buildSubwayMap(system(), 'naif-999', ['naif-499']);
		expect(map.routes).toEqual([]);
		expect(map.stations).toEqual([]);
	});

	it('prices a fall into low solar orbit as a bound arrival at the root', () => {
		const map = buildSubwayMap(system(), 'naif-399', ['naif-10']);
		const r = route(map, 'naif-10');
		expect(r.path).toEqual([
			stationId('surface', 'naif-399'),
			stationId('orbit', 'naif-399'),
			stationId('escape', 'naif-399'),
			stationId('transfer', 'naif-10'),
			stationId('orbit', 'naif-10')
		]);
		// Killing most of Earth's orbital speed, priced with Oberth at LEO.
		const depart = edge(map, r.path[2], r.path[3]).dvKms;
		expect(depart).toBeGreaterThan(17.5);
		expect(depart).toBeLessThan(18.5);
		// Circularising 200 km over the photosphere: absurd, and shown as is.
		const arrive = edge(map, r.path[3], r.path[4]).dvKms;
		expect(arrive).toBeGreaterThan(170);
		expect(arrive).toBeLessThan(190);
		expect(r.surfaceKms).toBeNull();
		expect(r.transferDays).toBeGreaterThan(60);
		expect(r.transferDays).toBeLessThan(70);
	});

	it('adds the origin stationary orbit as a two-stop row off low orbit', () => {
		const map = buildSubwayMap(system(), 'naif-399', ['naif-499']);
		const r = map.routes.find((x) => x.kind === 'stationary');
		expect(r).toBeDefined();
		expect(r!.targetId).toBe('naif-399');
		expect(r!.path).toEqual([
			stationId('surface', 'naif-399'),
			stationId('orbit', 'naif-399'),
			stationId('transfer', 'naif-399'),
			stationId('stationary', 'naif-399')
		]);
		const gto = edge(map, r!.path[1], r!.path[2]).dvKms;
		const circ = edge(map, r!.path[2], r!.path[3]).dvKms;
		expect(gto).toBeGreaterThan(2.4);
		expect(gto).toBeLessThan(2.5);
		expect(circ).toBeGreaterThan(1.4);
		expect(circ).toBeLessThan(1.5);
		expect(r!.transferDays).toBeGreaterThan(0.2);
		expect(r!.transferDays).toBeLessThan(0.25);
	});

	it('offers no stationary row where the spin is unknown', () => {
		const map = buildSubwayMap(system(), 'naif-301', ['naif-399']);
		expect(map.routes.some((x) => x.kind === 'stationary')).toBe(false);
	});

	it('prices leaving the Solar System as the last stop off escape', () => {
		const map = buildSubwayMap(system(), 'naif-399', ['naif-499']);
		const r = map.routes.find((x) => x.kind === 'escape')!;
		expect(r.targetId).toBe('naif-10');
		expect(r.path.slice(-2)).toEqual([
			stationId('escape', 'naif-399'),
			stationId('escape', 'naif-10')
		]);
		// LEO to solar escape is 8.7–8.8 km/s in the literature; 3.23 of it is Earth escape.
		const extra = edge(map, r.path[2], r.path[3]).dvKms;
		expect(extra).toBeGreaterThan(5.3);
		expect(extra).toBeLessThan(5.7);
		expect(r.transferDays).toBe(Infinity);
	});

	it('routes the Solar System escape through Earth from the Moon', () => {
		const map = buildSubwayMap(system(), 'naif-301', []);
		const r = map.routes.find((x) => x.kind === 'escape')!;
		// The ladder all the way up: the Moon's well, then Earth's, then the Sun's.
		expect(r.path).toEqual([
			stationId('surface', 'naif-301'),
			stationId('orbit', 'naif-301'),
			stationId('escape', 'naif-301'),
			stationId('escape', 'naif-399'),
			stationId('escape', 'naif-10')
		]);
		// Leaving the Solar System costs the same however the climb is split.
		const oneStep = buildSubwayMap(system(), 'naif-399', []).routes.find(
			(x) => x.kind === 'escape'
		)!;
		expect(r.orbitKms).toBeLessThan(oneStep.orbitKms);
	});
});
