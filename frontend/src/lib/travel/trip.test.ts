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
			aero: 'aerobraking',
			timeMode: 'arrive',
			pickedJd: DEPART_JD,
			vehicleId: 'nuclear-thermal-stage',
			passengers: 4,
			payloadKg: 12500,
			profile: 'custom',
			pick: { departJd: 2463000.25, tofDays: 214.5 }
		};
		expect(reparse(trip)).toEqual(trip);
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
