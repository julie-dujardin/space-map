import { describe, it, expect } from 'vitest';
import { dateToJD } from '$lib/format/date';
import { DEFAULT_TRIP, parseTrip, serializeTripSuffix, type TripState } from './trip';

/** Read a suffix back the way `parseUrl` does — as the query it becomes. */
function reparse(trip: TripState): TripState {
	return parseTrip(new URLSearchParams(serializeTripSuffix(trip).replace(/^&/, '')));
}

const DEPART_JD = dateToJD(new Date('2033-04-12T06:30:00Z'));

describe('serializeTripSuffix', () => {
	it('writes nothing for a form nobody has touched', () => {
		expect(serializeTripSuffix(DEFAULT_TRIP)).toBe('');
	});

	it('starts with & so it concatenates after the camera block', () => {
		expect(serializeTripSuffix({ ...DEFAULT_TRIP, targetMode: 'flyby' })).toBe('&tm=flyby');
	});

	// Nothing is chosen until someone chooses it, so the term is absent while the
	// trip is still a list of options and present the moment one is being read.
	it('writes the route only once one is chosen', () => {
		expect(serializeTripSuffix({ ...DEFAULT_TRIP, profile: null })).toBe('');
		expect(serializeTripSuffix({ ...DEFAULT_TRIP, profile: 'balanced' })).toBe('&route=balanced');
		expect(serializeTripSuffix({ ...DEFAULT_TRIP, profile: 'efficient' })).toBe('&route=efficient');
	});

	// The mode is only meaningful with a date; without one it searches exactly
	// the span "now" does.
	it('leaves out a dateless depart/arrive mode', () => {
		expect(serializeTripSuffix({ ...DEFAULT_TRIP, timeMode: 'depart', pickedJd: null })).toBe('');
	});

	// Somewhere with air uses the air by default, so only turning that down is a
	// choice worth carrying in a link.
	it('writes the aero term only when it is not the default', () => {
		expect(serializeTripSuffix({ ...DEFAULT_TRIP, aero: 'aerocapture' })).toBe('');
		expect(serializeTripSuffix({ ...DEFAULT_TRIP, aero: 'none' })).toBe('&aero=none');
	});

	it('leaves out a date the mode does not use', () => {
		expect(serializeTripSuffix({ ...DEFAULT_TRIP, timeMode: 'now', pickedJd: DEPART_JD })).toBe('');
	});
});

describe('trip URL round trip', () => {
	it('carries every term of a fully described trip', () => {
		const trip: TripState = {
			originMode: 'low-orbit',
			targetMode: 'elliptical',
			originAltKm: DEFAULT_TRIP.originAltKm,
			targetAltKm: DEFAULT_TRIP.targetAltKm,
			originApoAltKm: DEFAULT_TRIP.originApoAltKm,
			targetApoAltKm: DEFAULT_TRIP.targetApoAltKm,
			originIncDeg: null,
			targetIncDeg: null,
			originArgPeriDeg: null,
			targetArgPeriDeg: null,
			aero: 'aerobraking',
			timeMode: 'arrive',
			pickedJd: DEPART_JD,
			vehicleId: 'nuclear-thermal-stage',
			passengers: 4,
			payloadKg: 12500,
			profile: 'custom',
			pick: { departJd: 2463000.25, tofDays: 214.5 },
			coastFraction: 0.4
		};
		expect(reparse(trip)).toEqual(trip);
	});

	// A plane is what tells two otherwise identical trips apart, so an unnamed one
	// has to come back unnamed rather than as the equator.
	it('leaves a plane nobody named out of the link', () => {
		expect(serializeTripSuffix(DEFAULT_TRIP)).toBe('');
		expect(reparse(DEFAULT_TRIP).originIncDeg).toBeNull();
		// Nought is a plane like any other — the equator — and has to survive the trip.
		const equatorial = { ...DEFAULT_TRIP, originMode: 'custom' as const, originIncDeg: 0 };
		expect(reparse(equatorial).originIncDeg).toBe(0);
	});

	// The custom orbit is the only one with a plane to set, so it is the only mode
	// the plane rides along with — the same rule its altitude follows.
	it('carries the plane only alongside the orbit that has one', () => {
		const custom = { ...DEFAULT_TRIP, targetMode: 'custom' as const, targetIncDeg: 45 };
		expect(serializeTripSuffix(custom)).toContain('tinc=45');
		expect(
			serializeTripSuffix({ ...DEFAULT_TRIP, targetMode: 'stationary', targetIncDeg: 45 })
		).not.toContain('tinc');
	});

	// A circular custom orbit is one altitude, which is what every link written
	// before the orbit had two ends says, so the far end is written only where it
	// is somewhere else.
	it('writes the far end of the orbit only where it is one', () => {
		const circular = { ...DEFAULT_TRIP, targetMode: 'custom' as const, targetAltKm: 800 };
		expect(serializeTripSuffix({ ...circular, targetApoAltKm: 800 })).not.toContain('tapo');
		const ellipse = { ...circular, targetApoAltKm: 39750 };
		expect(serializeTripSuffix(ellipse)).toContain('tapo=39750');
		expect(reparse(ellipse).targetApoAltKm).toBe(39750);
	});

	// The near end of a custom orbit carries the far one up with it, so a far end
	// left below it is a stale figure and not a shape anybody asked for. Writing it
	// would hand back the orbit inside out, since the ends are sorted on the way in.
	it('never names the orbit backwards', () => {
		const stale = {
			...DEFAULT_TRIP,
			targetMode: 'custom' as const,
			targetAltKm: 130925,
			targetApoAltKm: 39750
		};
		expect(serializeTripSuffix(stale)).not.toContain('tapo');
		expect(reparse(stale).targetApoAltKm).toBe(130925);
	});

	// The link says an orbit, not the order its ends were written in.
	it('reads an orbit named the other way round as the same orbit', () => {
		const trip = parseTrip(new URLSearchParams('tm=custom&talt=39750&tapo=600'));
		expect([trip.targetAltKm, trip.targetApoAltKm]).toEqual([600, 39750]);
	});

	// An angle round the orbit needs a plane to be measured from and an ellipse to
	// be an angle on, so a circle or a free plane carries none — it would name a
	// point on the orbit that does not exist.
	it('carries the argument of periapsis only where it says something', () => {
		const molniya = {
			...DEFAULT_TRIP,
			targetMode: 'custom' as const,
			targetAltKm: 600,
			targetApoAltKm: 39750,
			targetIncDeg: 63.4,
			targetArgPeriDeg: 270
		};
		expect(serializeTripSuffix(molniya)).toContain('targp=270');
		expect(reparse(molniya).targetArgPeriDeg).toBe(270);
		// Take the plane away and it is measured from nothing; round the orbit off
		// and there is no low point to be an angle to.
		expect(serializeTripSuffix({ ...molniya, targetIncDeg: null })).not.toContain('targp');
		expect(serializeTripSuffix({ ...molniya, targetApoAltKm: 600 })).not.toContain('targp');
	});

	// It runs the whole way round, unlike a plane, so it wraps rather than sticks.
	it('wraps an angle past a full turn', () => {
		expect(parseTrip(new URLSearchParams('targp=390')).targetArgPeriDeg).toBe(30);
		expect(parseTrip(new URLSearchParams('targp=-90')).targetArgPeriDeg).toBe(270);
	});

	it('keeps the picked date to the second', () => {
		const trip: TripState = { ...DEFAULT_TRIP, timeMode: 'depart', pickedJd: DEPART_JD };
		expect(reparse(trip).pickedJd).toBeCloseTo(DEPART_JD, 6);
	});
});

describe('parseTrip', () => {
	it('falls back to the default for a term it does not recognise', () => {
		const params = new URLSearchParams('fm=hyperbolic&tm=nonsense&route=cheapest&craft=');
		expect(parseTrip(params)).toEqual(DEFAULT_TRIP);
	});

	// Only a destination can be flown past or held in a loose ellipse.
	it('rejects a departure mode only a destination has', () => {
		expect(parseTrip(new URLSearchParams('fm=flyby')).originMode).toBe('surface');
		expect(parseTrip(new URLSearchParams('tm=flyby')).targetMode).toBe('flyby');
	});

	it('reads nothing aboard from a manifest that makes no sense', () => {
		const trip = parseTrip(new URLSearchParams('crew=-3&cargo=lots'));
		expect(trip.passengers).toBe(0);
		expect(trip.payloadKg).toBe(0);
	});

	it('floors a fractional crew', () => {
		expect(parseTrip(new URLSearchParams('crew=2.7')).passengers).toBe(2);
	});

	it('drops a date it cannot read', () => {
		expect(parseTrip(new URLSearchParams('when=depart,sometime'))).toEqual(DEFAULT_TRIP);
		expect(parseTrip(new URLSearchParams('when=depart'))).toEqual(DEFAULT_TRIP);
	});

	// A cruise of no length is not an arc, and half a pair names no point.
	it('drops a pick that is not a point on the field', () => {
		expect(parseTrip(new URLSearchParams('pick=2463000.25,0')).pick).toBeNull();
		expect(parseTrip(new URLSearchParams('pick=2463000.25')).pick).toBeNull();
	});
});
