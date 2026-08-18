import { describe, it, expect } from 'vitest';
import {
	BELT_PROFILES,
	beltPassDoseGy,
	MODELLED_BELT_IDS,
	buildRoute,
	buildTrajectoryPath,
	DEFAULT_SHIELDING_G_CM2,
	type Route,
	type TravelBody,
	type Vehicle
} from '$lib/math/travel';
import { craftPositionAt } from '$lib/math/travel/path-sample';
import { hohmannTransferDays, nextTransferWindows } from '$lib/math/travel/windows';
import { findAssistRoute } from '$lib/math/travel/assist';
import {
	EARTH,
	J2000,
	JUPITER,
	MARS,
	MERCURY,
	MOON_BARYCENTRIC,
	EARTH_BARYCENTRIC,
	MOON,
	SATURN,
	VENUS
} from '$lib/math/travel/test-fixtures';
import { adjustForVehicle, routeHazards, type Hazard, type HazardKind } from './hazards';
import { equilibriumTempK, sunsAt } from './sunlight';

const SUN = 'naif-10';
const HELIOCENTRIC = { centerId: SUN } as const;

/** The route the two bodies' next window offers, on a Hohmann-length crossing. */
function transfer(from: TravelBody, to: TravelBody, options = {}): Route {
	const depart = nextTransferWindows(from, to, J2000, 1)[0];
	const tof = hohmannTransferDays(from, to)!;
	return buildRoute(from, to, depart, tof, options)!;
}

function of<T extends Hazard>(hazards: readonly T[], kind: HazardKind): T | undefined {
	return hazards.find((hazard) => hazard.kind === kind);
}

/**
 * A body on a circular orbit at `au`, so a trajectory can be aimed somewhere the
 * real solar system has nothing. Massless enough that the arrival costs nothing
 * to speak of — the point of these is where the arc goes, not what it costs.
 */
function bodyAt(id: string, au: number): TravelBody {
	return {
		id,
		mu: 1000,
		muEstimated: true,
		radiusKm: 100,
		elements: {
			a: au,
			e: 0,
			i: 0,
			om: 0,
			w: 0,
			ma: 0,
			n: (360 / 365.25) * Math.pow(au, -1.5),
			epoch: J2000
		}
	};
}

describe('sunlight', () => {
	it('is an inverse square about 1 AU', () => {
		expect(sunsAt(1)).toBeCloseTo(1, 10);
		expect(sunsAt(0.5)).toBeCloseTo(4, 10);
		// Mars at its aphelion, 1.666 AU: the figure the panel quotes as 36%.
		expect(sunsAt(1.666)).toBeCloseTo(0.36, 2);
		// Jupiter, where Juno flies 60 m² of cells for 486 W.
		expect(sunsAt(5.2)).toBeCloseTo(0.037, 3);
	});

	it('gives the textbook equilibrium temperatures', () => {
		// Earth's own blackbody temperature, the anchor the scaling is written for.
		expect(equilibriumTempK(1)).toBeCloseTo(278.6, 1);
		// Inside Mercury's perihelion, where a sunshade stops being optional.
		expect(equilibriumTempK(0.3)).toBeGreaterThan(500);
	});
});

describe('routeHazards', () => {
	it('calls a Mars crossing dim but not dark, and never hot', () => {
		const hazards = routeHazards(EARTH, MARS, transfer(EARTH, MARS), HELIOCENTRIC);

		const power = of(hazards, 'solar-power');
		expect(power?.severity).toBe('notice');
		// Somewhere between Mars at perihelion and Mars at aphelion — which is the
		// whole span the threshold was placed to cover.
		expect(power!.peak).toBeGreaterThan(0.35);
		expect(power!.peak).toBeLessThan(0.53);
		expect(power!.auAtPeak).toBeGreaterThan(1.37);

		expect(of(hazards, 'solar-heat')).toBeUndefined();
	});

	it('stops short of calling Jupiter beyond solar power', () => {
		// Juno, JUICE and Europa Clipper all fly there on panels — enormous ones,
		// which is the middle tier and not the top one.
		const hazards = routeHazards(EARTH, JUPITER, transfer(EARTH, JUPITER), HELIOCENTRIC);

		const power = of(hazards, 'solar-power');
		expect(power?.severity).toBe('caution');
		expect(power!.peak).toBeLessThan(0.05);
		// The dark stretch starts partway out, not at departure.
		expect(power!.startJd).toBeGreaterThan(hazards[0].startJd - 1e9);
		expect(power!.peakJd).toBeCloseTo(power!.endJd, 0);
	});

	it('calls Saturn beyond it, where nothing solar has been', () => {
		const hazards = routeHazards(EARTH, SATURN, transfer(EARTH, SATURN), HELIOCENTRIC);
		const power = of(hazards, 'solar-power');
		expect(power?.severity).toBe('severe');
		expect(power!.auAtPeak).toBeGreaterThan(5.5);
	});

	it('leaves a trip to Mars at the mildest tier', () => {
		// Plenty of solar spacecraft go to Mars; the threshold above it is placed
		// clear of its aphelion so none of them reads as a problem.
		const power = of(routeHazards(EARTH, MARS, transfer(EARTH, MARS), HELIOCENTRIC), 'solar-power');
		expect(power?.severity).toBe('notice');
	});

	it('does not raise a power hazard on a trip that stays near Earth', () => {
		const hazards = routeHazards(EARTH, VENUS, transfer(EARTH, VENUS), HELIOCENTRIC);
		expect(of(hazards, 'solar-power')).toBeUndefined();
	});

	it('reads the heat off the closest approach to the Sun, not off the destination', () => {
		const hazards = routeHazards(EARTH, MERCURY, transfer(EARTH, MERCURY), HELIOCENTRIC);
		const heat = of(hazards, 'solar-heat');
		expect(heat).toBeDefined();
		// Mercury's own orbit runs 0.31–0.47 AU, so the arc gets at least 4.5 suns.
		expect(heat!.peak).toBeGreaterThan(4.5);
		expect(heat!.auAtPeak).toBeLessThan(0.48);
		expect(heat!.severity).not.toBe('notice');
	});

	it('escalates a sun-grazing arc past what a sunshade is built for', () => {
		const grazer = bodyAt('test-grazer', 0.2);
		const hazards = routeHazards(EARTH, grazer, transfer(EARTH, grazer), HELIOCENTRIC);
		const heat = of(hazards, 'solar-heat');
		// 0.2 AU is 25 suns, well past the 11 that separates thermal design from a
		// sunshade — and it is the whole reason this is severe rather than caution.
		expect(heat?.severity).toBe('severe');
		expect(heat!.peak).toBeGreaterThan(11);
		expect(heat!.startJd).toBeLessThan(heat!.peakJd);
	});

	it('stays under the heat threshold just outside it', () => {
		// 0.75 AU is 1.78 suns: hot, and not two.
		const warm = bodyAt('test-warm', 0.75);
		const hazards = routeHazards(EARTH, warm, transfer(EARTH, warm), HELIOCENTRIC);
		expect(of(hazards, 'solar-heat')).toBeUndefined();
	});

	it('reports the lag from the place the trip left', () => {
		const hazards = routeHazards(EARTH, MARS, transfer(EARTH, MARS), HELIOCENTRIC);
		const lag = of(hazards, 'signal-lag');
		expect(lag).toBeDefined();
		// Mars at its furthest is 22 light-minutes; a transfer arc never gets there,
		// but it does get past the five minutes that ends real-time supervision.
		expect(lag!.peak).toBeGreaterThan(300);
		expect(lag!.peak).toBeLessThan(22 * 60);
	});

	it('finds the fortnight a long crossing spends behind the Sun', () => {
		// Six years to Saturn is six Earth years under it, so the craft passes
		// through conjunction several times; the one reported is the worst.
		const hazards = routeHazards(EARTH, SATURN, transfer(EARTH, SATURN), HELIOCENTRIC);
		const conjunction = of(hazards, 'conjunction');
		// One tier however close it gets: a fortnight of silence is something to
		// know, not something a different spacecraft would answer.
		expect(conjunction?.severity).toBe('notice');
		expect(conjunction!.peak).toBeLessThan(2);
		// A blackout is days to weeks. One that came out months long would mean the
		// stretch had been drawn across several separate episodes.
		const days = conjunction!.endJd - conjunction!.startJd;
		expect(days).toBeGreaterThan(1);
		expect(days).toBeLessThan(40);
		expect(conjunction!.peakJd).toBeGreaterThanOrEqual(conjunction!.startJd);
		expect(conjunction!.peakJd).toBeLessThanOrEqual(conjunction!.endJd);
	});

	it('does not raise one on a crossing that never passes behind the Sun', () => {
		// Earth → Mars on its own window stays well clear: the craft leads Earth the
		// whole way and never drops inside five degrees of the Sun.
		expect(
			of(routeHazards(EARTH, MARS, transfer(EARTH, MARS), HELIOCENTRIC), 'conjunction')
		).toBeUndefined();
	});

	it('says nothing about the Sun on a trip inside one system', () => {
		const route = buildRoute(EARTH_BARYCENTRIC, MOON_BARYCENTRIC, J2000, 3, {
			centralMu: EARTH_BARYCENTRIC.mu + MOON_BARYCENTRIC.mu,
			systemPrimary: 'departure'
		})!;
		const hazards = routeHazards(EARTH_BARYCENTRIC, MOON_BARYCENTRIC, route, {
			// Distances here are from the Earth–Moon barycentre, so nothing about
			// sunlight or about the Sun being in the way can be read off them.
			centerId: 'naif-3',
			centralMu: EARTH_BARYCENTRIC.mu + MOON_BARYCENTRIC.mu,
			systemPrimary: 'departure'
		});
		expect(of(hazards, 'solar-power')).toBeUndefined();
		expect(of(hazards, 'solar-heat')).toBeUndefined();
		expect(of(hazards, 'conjunction')).toBeUndefined();
	});

	it('reads a trip whose frame is centred on the Sun, not just a heliocentric one', () => {
		// Earth → the Sun is a *system* transfer whose primary happens to be the
		// Sun, and a trip between two comets is a *sibling* one about it. Both
		// measure from the Sun; neither is what the kernel calls heliocentric, so
		// judging by transfer kind rather than by centre would miss both.
		const inner = bodyAt('test-inner', 0.25);
		const sibling = routeHazards(EARTH, inner, transfer(EARTH, inner), { centerId: 'naif-0' });
		expect(of(sibling, 'solar-heat')?.severity).toBe('severe');
	});

	it('reads nothing off the stretch of arc that runs into the body it ends at', () => {
		// Past the trim the conic carries on to the destination's centre, which is
		// not where the craft goes. Read whole, a trip to a body at 0.25 AU would
		// find samples at nought AU and report an infinity of sunlight.
		const inner = bodyAt('test-inner', 0.25);
		const heat = of(routeHazards(EARTH, inner, transfer(EARTH, inner), HELIOCENTRIC), 'solar-heat');
		expect(heat!.peak).toBeLessThan(sunsAt(0.2));
		expect(Number.isFinite(heat!.peak)).toBe(true);
		expect(heat!.auAtPeak).toBeGreaterThan(0.2);
	});

	it('never escalates either of the two hazards about the link', () => {
		// Six years out and a third of a degree from the Sun is the worst either of
		// these gets in the solar system, and neither is a hardware problem: the lag
		// stops at the middle tier and the conjunction at the mildest.
		const hazards = routeHazards(EARTH, SATURN, transfer(EARTH, SATURN), HELIOCENTRIC);
		expect(of(hazards, 'signal-lag')!.severity).toBe('caution');
		expect(of(hazards, 'conjunction')!.severity).toBe('notice');
	});

	it('orders the worst first', () => {
		const hazards = routeHazards(EARTH, JUPITER, transfer(EARTH, JUPITER), HELIOCENTRIC);
		const rank = { notice: 0, caution: 1, severe: 2 };
		for (let i = 1; i < hazards.length; i++) {
			expect(rank[hazards[i - 1].severity]).toBeGreaterThanOrEqual(rank[hazards[i].severity]);
		}
	});
});

describe('the atmospheric arrival', () => {
	it('is raised for an aerocapture and not for a burn', () => {
		const aero = transfer(EARTH, MARS, { aero: 'aerocapture' });
		const propulsive = transfer(EARTH, MARS, { aero: 'none' });

		const entry = of(routeHazards(EARTH, MARS, aero, HELIOCENTRIC), 'aeroassist');
		expect(entry).toBeDefined();
		// Mars entry off an interplanetary approach: the 5–6 km/s every lander since
		// Viking has arrived at.
		expect(entry!.peak).toBeGreaterThan(4);
		expect(entry!.peak).toBeLessThan(8);
		expect(entry!.severity).toBe('notice');
		expect(entry!.startJd).toBeCloseTo(aero.arriveJd, 6);

		expect(of(routeHazards(EARTH, MARS, propulsive, HELIOCENTRIC), 'aeroassist')).toBeUndefined();
	});

	it('is not raised for an airless destination', () => {
		const route = buildRoute(EARTH, MOON, J2000, 3, {
			aero: 'aerocapture',
			centralMu: EARTH.mu,
			systemPrimary: 'departure'
		})!;
		expect(route.entrySpeedKms).toBeUndefined();
		const hazards = routeHazards(EARTH, MOON, route, { centerId: 'naif-399' });
		expect(of(hazards, 'aeroassist')).toBeUndefined();
	});

	it('covers the whole aerobraking campaign, not just the first pass', () => {
		const route = transfer(EARTH, MARS, { aero: 'aerobraking', arrivalMode: 'low-orbit' });
		const entry = of(routeHazards(EARTH, MARS, route, HELIOCENTRIC), 'aeroassist');
		expect(entry).toBeDefined();
		// Months of passes: the hazard outlasts the arrival it starts at, and the
		// first pass is the fastest one.
		expect(entry!.endJd).toBeGreaterThan(entry!.startJd + 1);
		expect(entry!.peakJd).toBe(entry!.startJd);
	});
});

describe('adjustForVehicle', () => {
	const base: Vehicle = { id: 'test', kind: 'probe', propulsion: 'chemical', status: 'active' };
	// Saturn rather than Jupiter: the softening has to be visible, and only past
	// Jupiter is the dark cruise called a problem in the first place.
	const saturn = routeHazards(EARTH, SATURN, transfer(EARTH, SATURN), HELIOCENTRIC);
	const saturnRoute = transfer(EARTH, SATURN);

	it('leaves the hazards alone when no craft is chosen', () => {
		expect(adjustForVehicle(saturn, null, saturnRoute).map((h) => h.severity)).toEqual(
			saturn.map((h) => h.severity)
		);
	});

	it('softens the dark cruise for a craft that does not run on sunlight', () => {
		const adjusted = adjustForVehicle(saturn, { ...base, power: 'rtg' }, saturnRoute);
		const power = of(adjusted, 'solar-power')!;
		expect(power.severity).toBe('notice');
		expect(adjusted.find((h) => h.kind === 'solar-power')?.craftNote).toEqual({
			kind: 'nuclear-power'
		});
		// The figure itself is a fact about the trip and does not move.
		expect(power.peak).toBe(of(saturn, 'solar-power')!.peak);
	});

	it('leaves it alone for a craft on solar panels', () => {
		const adjusted = adjustForVehicle(saturn, { ...base, power: 'solar' }, saturnRoute);
		expect(of(adjusted, 'solar-power')!.severity).toBe('severe');
	});

	it('sharpens an entry the craft is not rated for', () => {
		const route = transfer(EARTH, MARS, { aero: 'aerocapture' });
		const hazards = routeHazards(EARTH, MARS, route, HELIOCENTRIC);
		expect(of(hazards, 'aeroassist')!.severity).toBe('notice');

		const rated = { ...base, maxEntrySpeedKms: { value: 3, source: 'test' } };
		const adjusted = adjustForVehicle(hazards, rated, route);
		const entry = of(adjusted, 'aeroassist')!;
		expect(entry.severity).toBe('severe');
		expect(entry.craftNote).toEqual({ kind: 'entry-rating', ratedKms: 3 });
	});

	it('leaves an entry inside the rating alone', () => {
		const route = transfer(EARTH, MARS, { aero: 'aerocapture' });
		const hazards = routeHazards(EARTH, MARS, route, HELIOCENTRIC);
		const rated = { ...base, maxEntrySpeedKms: { value: 12, source: 'test' } };
		expect(of(adjustForVehicle(hazards, rated, route), 'aeroassist')!.severity).toBe('notice');
	});
});

describe('the stretch the map paints', () => {
	it('reddens into the worst of a hot approach rather than being red throughout', () => {
		const hazards = routeHazards(EARTH, MERCURY, transfer(EARTH, MERCURY), HELIOCENTRIC);
		const heat = of(hazards, 'solar-heat')!;
		const bands = heat.bands;
		expect(bands.length).toBeGreaterThan(1);

		// It starts milder than it ends up: crossing Venus's orbit is not yet what
		// perihelion is, and one colour for the whole stretch would say it was.
		expect(bands[0].severity).toBe('notice');
		expect(bands.map((band) => band.severity)).toContain(heat.severity);

		// End to end with no gaps, in flight order.
		expect(bands[0].startJd).toBeCloseTo(heat.startJd, 6);
		expect(bands[bands.length - 1].endJd).toBeCloseTo(heat.endJd, 6);
		for (let i = 1; i < bands.length; i++) {
			expect(bands[i].startJd).toBeCloseTo(bands[i - 1].endJd, 6);
			expect(bands[i].severity).not.toBe(bands[i - 1].severity);
		}
	});

	it('paints nothing for the two hazards that hold all the way across', () => {
		// A lag and a dark cruise are facts about the trip, not about a place on it:
		// banding them would colour the whole trajectory and bury the ones that are.
		const hazards = routeHazards(EARTH, SATURN, transfer(EARTH, SATURN), HELIOCENTRIC);
		expect(of(hazards, 'signal-lag')!.bands).toHaveLength(0);
		expect(of(hazards, 'solar-power')!.bands).toHaveLength(0);
		// The one that is a place keeps its stretch.
		expect(of(hazards, 'conjunction')!.bands.length).toBeGreaterThan(0);
	});

	it('paints nothing for an arrival, which happens where the arc ends', () => {
		const route = transfer(EARTH, MARS, { aero: 'aerocapture' });
		expect(of(routeHazards(EARTH, MARS, route, HELIOCENTRIC), 'aeroassist')!.bands).toHaveLength(0);
	});
});

describe('what the map is handed', () => {
	it('gives every hazard a date the drawn path has a point for', () => {
		const route = transfer(EARTH, JUPITER);
		const hazards = routeHazards(EARTH, JUPITER, route, HELIOCENTRIC);
		const path = buildTrajectoryPath(EARTH, JUPITER, route, { centerId: SUN })!;
		expect(hazards.length).toBeGreaterThan(0);

		for (const hazard of hazards) {
			// The arrival hazard can outlast the arc it arrives on — a braking
			// campaign is flown after the crossing ends — so only the start has to
			// land on the line.
			const point = craftPositionAt(path, hazard.startJd);
			expect(point, `${hazard.kind} at ${hazard.startJd}`).not.toBeNull();
			expect(Number.isFinite(point!.r[0])).toBe(true);
		}
	});

	it('scans at its own sample count, not the drawn one', () => {
		// Two calls, one of which would draw at 180 points and one at 64, must agree
		// about where every threshold falls — that is the whole reason the scan owns
		// its sampling instead of taking it from a caller.
		const route = transfer(EARTH, MERCURY);
		const a = routeHazards(EARTH, MERCURY, route, HELIOCENTRIC);
		const b = routeHazards(EARTH, MERCURY, route, { ...HELIOCENTRIC, vias: [VENUS] });
		expect(a.map((h) => [h.kind, h.severity])).toEqual(b.map((h) => [h.kind, h.severity]));
	});
});

describe('a trajectory whose geometry cannot be rebuilt', () => {
	it('still reports what the route itself says', () => {
		const route = transfer(EARTH, MARS, { aero: 'aerocapture' });
		// A swing-by route with no via body cannot be drawn; the same is true of any
		// route the propagator will not close. What the ladder knows survives it.
		const broken: Route = {
			...route,
			flybys: [
				{
					bodyId: 'naif-299',
					jd: route.departJd + 50,
					altitudeKm: 500,
					turnDeg: 30,
					dvKms: 0,
					vInfInKms: 3,
					vInfOutKms: 3
				}
			]
		};
		const hazards = routeHazards(EARTH, MARS, broken, HELIOCENTRIC);
		expect(of(hazards, 'aeroassist')).toBeDefined();
		expect(of(hazards, 'solar-power')).toBeUndefined();
	});
});

describe('radiation', () => {
	it('costs a crossing to Mars something in the range Guo measured', () => {
		const hazards = routeHazards(EARTH, MARS, transfer(EARTH, MARS), HELIOCENTRIC);
		const dose = of(hazards, 'radiation')!;
		expect(dose).toBeDefined();
		// One way, so roughly half of the 0.65-1.59 Sv Guo puts a round trip at.
		expect(dose.peak).toBeGreaterThan(0.15);
		expect(dose.peak).toBeLessThan(0.6);
	});

	it('carries the rate as well as the total, because the two differ', () => {
		const hazards = routeHazards(EARTH, MARS, transfer(EARTH, MARS), HELIOCENTRIC);
		const dose = of(hazards, 'radiation')!;
		// Free space at 1 au is about 1.2 mSv/day over a cycle.
		expect(dose.rateAtPeak).toBeGreaterThan(5e-4);
		expect(dose.rateAtPeak).toBeLessThan(5e-3);
	});

	it('charges a longer crossing more than a shorter one', () => {
		const toMars = of(routeHazards(EARTH, MARS, transfer(EARTH, MARS), HELIOCENTRIC), 'radiation')!;
		const toSaturn = of(
			routeHazards(EARTH, SATURN, transfer(EARTH, SATURN), HELIOCENTRIC),
			'radiation'
		)!;
		expect(toSaturn.peak).toBeGreaterThan(toMars.peak);
	});

	it('says nothing rather than something false inside a planet system', () => {
		// A planetocentric radius is not an AU, and reading it as one would put
		// the craft a thousand times too close to the Sun.
		const route = buildRoute(EARTH_BARYCENTRIC, MOON_BARYCENTRIC, J2000, 4, {
			systemPrimary: 'departure'
		})!;
		const hazards = routeHazards(EARTH_BARYCENTRIC, MOON_BARYCENTRIC, route, {
			centerId: EARTH_BARYCENTRIC.id,
			systemPrimary: 'departure'
		});
		expect(of(hazards, 'radiation')).toBeUndefined();
	});

	it('is not banded, because the rate barely varies along a crossing', () => {
		const hazards = routeHazards(EARTH, MARS, transfer(EARTH, MARS), HELIOCENTRIC);
		expect(of(hazards, 'radiation')!.bands).toHaveLength(0);
	});
});

describe('belt crossings', () => {
	const toSaturnViaJupiter = () =>
		findAssistRoute(EARTH, SATURN, [JUPITER], { nowJd: J2000, departureMode: 'orbit' })!;

	it('prices the swing-by the solver actually picks, which is a distant one', () => {
		// Worth pinning because it is the opposite of the intuition. The free
		// pass past Jupiter is solved for the turn it needs and lands around 14
		// planetary radii, well outside the belt peak, so it costs a fraction of
		// a gray rather than the hundreds a close pass would.
		const route = toSaturnViaJupiter();
		const belt = of(
			routeHazards(EARTH, SATURN, route, { ...HELIOCENTRIC, vias: [JUPITER] }),
			'belt-crossing'
		)!;
		expect(belt).toBeDefined();
		expect(belt.bodyId).toBe(JUPITER.id);
		expect(route.flybys![0].altitudeKm / JUPITER.radiusKm).toBeGreaterThan(5);
		expect(belt.peak).toBeGreaterThan(0.1);
		expect(belt.peak).toBeLessThan(4);
	});

	it('would charge a close pass three orders of magnitude more', () => {
		// The case the model exists for, and the reason a Δv ladder is not
		// enough to choose a trajectory by: these two passes cost the same fuel.
		const distant = beltPassDoseGy(
			BELT_PROFILES['naif-599'],
			14 * JUPITER.radiusKm,
			5.6,
			DEFAULT_SHIELDING_G_CM2,
			JUPITER.radiusKm,
			JUPITER.mu
		);
		const close = beltPassDoseGy(
			BELT_PROFILES['naif-599'],
			2 * JUPITER.radiusKm,
			5.6,
			DEFAULT_SHIELDING_G_CM2,
			JUPITER.radiusKm,
			JUPITER.mu
		);
		expect(close / distant).toBeGreaterThan(100);
		// Half of unaided survival is around 4 Gy.
		expect(close).toBeGreaterThan(100);
	});

	it('puts the pass at the moment it happens, not across the trip', () => {
		const route = toSaturnViaJupiter();
		const belt = of(
			routeHazards(EARTH, SATURN, route, { ...HELIOCENTRIC, vias: [JUPITER] }),
			'belt-crossing'
		)!;
		expect(belt.startJd).toBe(route.flybys![0].jd);
		expect(belt.endJd).toBe(belt.startJd);
	});

	it('prices a Saturn pass rather than declining to, and finds it mild', () => {
		// SATRAD put a dose against distance on Saturn's belts, so this stopped
		// being unpriced. A pass gentle enough to fall under the first band is
		// dropped entirely, which is the right answer and not a missing one.
		const route = findAssistRoute(EARTH, JUPITER, [SATURN], {
			nowJd: J2000,
			departureMode: 'orbit'
		});
		if (!route?.flybys?.length) return;
		const belt = of(
			routeHazards(EARTH, JUPITER, route, { ...HELIOCENTRIC, vias: [SATURN] }),
			'belt-crossing'
		);
		expect(belt?.unpriced).toBeUndefined();
	});

	it('says a belt was crossed and declines to price it where nobody has', () => {
		// Uranus and Earth: a belt everyone agrees is there, and no dose
		// against distance published for either.
		expect(MODELLED_BELT_IDS.has('naif-799')).toBe(false);
		expect(MODELLED_BELT_IDS.has('naif-399')).toBe(false);
	});

	it('leaves a route with no swing-by alone', () => {
		const hazards = routeHazards(EARTH, MARS, transfer(EARTH, MARS), HELIOCENTRIC);
		expect(of(hazards, 'belt-crossing')).toBeUndefined();
	});
});
