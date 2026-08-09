import { describe, it, expect } from 'vitest';
import { EARTH, J2000, JUPITER, MARS, SATURN } from '$lib/math/travel/test-fixtures';
import { buildAssistRoute, buildConstantThrustRoute, type Vehicle } from '$lib/math/travel';
import { TravelPanelState } from './panel.svelte';
import { DEFAULT_TRIP } from './trip';

describe('TravelPanelState arrival mode', () => {
	it('maps each destination mode onto the kernel case it means', () => {
		const panel = new TravelPanelState();
		panel.targetMode = 'surface';
		expect(panel.arrivalMode).toBe('landing');
		panel.targetMode = 'low-orbit';
		expect(panel.arrivalMode).toBe('low-orbit');
		panel.targetMode = 'elliptical';
		expect(panel.arrivalMode).toBe('capture');
		panel.targetMode = 'flyby';
		expect(panel.arrivalMode).toBe('flyby');
	});

	// The mode picker is hidden for a named place, so whatever it last held is
	// stale — a crater can only be landed in.
	it('lands on a surface feature whatever the picker last held', () => {
		const panel = new TravelPanelState();
		panel.targetMode = 'flyby';
		panel.targetIsFeature = true;
		expect(panel.arrivalMode).toBe('landing');
	});
});

describe('TravelPanelState departure mode', () => {
	it('leaves from the ground or from a parking orbit', () => {
		const panel = new TravelPanelState();
		panel.originMode = 'surface';
		expect(panel.departureMode).toBe('surface');
		panel.originMode = 'low-orbit';
		expect(panel.departureMode).toBe('orbit');
	});

	it('launches from the ground when the departure is a place on one', () => {
		const panel = new TravelPanelState();
		panel.originMode = 'low-orbit';
		panel.originIsFeature = true;
		expect(panel.departureMode).toBe('surface');
	});
});

describe('TravelPanelState hand-picked windows', () => {
	/** The middle of the grid — a point the solver would not have offered. */
	function centre(panel: TravelPanelState): [number, number] {
		const grid = panel.grid!;
		const depart = (grid.departJds[0] + grid.departJds[grid.departSteps - 1]) / 2;
		const tof = (grid.tofDays[0] + grid.tofDays[grid.tofSteps - 1]) / 2;
		return [depart, tof];
	}

	async function solved(): Promise<TravelPanelState> {
		const panel = new TravelPanelState();
		await panel.solve(EARTH, MARS, J2000);
		return panel;
	}

	it('prices a point read off the field and flies it', async () => {
		const panel = await solved();
		const [depart, tof] = centre(panel);
		panel.pickCustom(depart, tof);

		expect(panel.selectedProfile).toBe('custom');
		expect(panel.selectedRoute?.departJd).toBeCloseTo(depart, 6);
		expect(panel.selectedRoute?.tofDays).toBeCloseTo(tof, 6);
		expect(panel.offered).toHaveLength(panel.routes.length + 1);
		expect(panel.offered.at(-1)?.profile).toBe('custom');
	});

	// Changing how the trip is flown is a change to what the same window costs.
	it('keeps the pick across a re-solve, re-priced', async () => {
		const panel = await solved();
		const [depart, tof] = centre(panel);
		panel.pickCustom(depart, tof);
		const fromOrbit = panel.custom!.totalDvKms;

		panel.originMode = 'low-orbit';
		await panel.solve(EARTH, MARS, J2000);

		expect(panel.selectedProfile).toBe('custom');
		expect(panel.custom?.departJd).toBeCloseTo(depart, 6);
		// The ascent is gone, so the same arc is cheaper than it was off the ground.
		expect(panel.custom!.totalDvKms).toBeLessThan(fromOrbit);
	});

	it('drops the pick when the trip is no longer between the same two bodies', async () => {
		const panel = await solved();
		panel.pickCustom(...centre(panel));

		await panel.solve(MARS, EARTH, J2000);

		expect(panel.custom).toBeNull();
		expect(panel.selectedProfile).not.toBe('custom');
	});
});

describe('TravelPanelState constant-thrust arc', () => {
	/** A torch ship: an acceleration to hold, and the propellant to hold it. */
	const ROCINANTE = {
		id: 'rocinante',
		kind: 'crewed',
		status: 'fiction',
		unlimitedDv: true,
		accelMs2: { value: 3.27, source: 'test' }
	} as unknown as Vehicle;

	function torched(): TravelPanelState {
		const panel = new TravelPanelState();
		panel.torch = buildConstantThrustRoute(EARTH, MARS, J2000, 3.27, { departureMode: 'orbit' });
		return panel;
	}

	// It leads rather than trails the way a hand-picked window does: the only
	// craft it is offered for cannot fly any of the others.
	it('leads the list, ahead of the solver\u2019s own', () => {
		const panel = torched();
		expect(panel.offered.map((choice) => choice.profile)).toEqual(['constant-thrust']);
		expect(panel.selectedRoute?.constantThrust).toBe(3.27);
	});

	it('offers nothing once the arc is withdrawn and no search has landed', () => {
		const panel = torched();
		panel.selectedProfile = 'constant-thrust';
		panel.torch = null;
		expect(panel.offered).toEqual([]);
		expect(panel.selectedRoute).toBeNull();
	});

	// Arriving with a torch ship is not the same as picking one: the link already
	// said which trajectory it meant, and the arc selects itself on the choice.
	//
	// The catalogue is fetched, so this runs once with the craft still unresolved
	// before it runs with the craft in hand — which is the order that actually
	// broke it, and why the first pass is here rather than assumed away.
	it('leaves a trajectory the trip arrived naming alone', async () => {
		const panel = new TravelPanelState({
			...DEFAULT_TRIP,
			vehicleId: 'rocinante',
			profile: 'fast'
		});
		await panel.solve(EARTH, MARS, J2000);

		panel.updateTorch(EARTH, MARS, J2000);
		expect(panel.torch).toBeNull();

		panel.acceptVehicles([ROCINANTE]);
		panel.updateTorch(EARTH, MARS, J2000);

		expect(panel.torch).not.toBeNull();
		expect(panel.selectedProfile).toBe('fast');
	});

	// The arc is the one trajectory that cannot be priced until the catalogue is
	// in, so the pass before it lands must not read as "no such trajectory" and
	// drop the very selection the link arrived with.
	it('keeps the arc a trip arrived selecting, across the wait for the catalogue', async () => {
		const panel = new TravelPanelState({
			...DEFAULT_TRIP,
			vehicleId: 'rocinante',
			profile: 'constant-thrust'
		});
		await panel.solve(EARTH, MARS, J2000);

		panel.updateTorch(EARTH, MARS, J2000);
		expect(panel.selectedProfile).toBe('constant-thrust');

		panel.acceptVehicles([ROCINANTE]);
		panel.updateTorch(EARTH, MARS, J2000);

		expect(panel.torch).not.toBeNull();
		expect(panel.selectedProfile).toBe('constant-thrust');
	});

	// A craft the catalogue has no entry for is a real answer, not a wait: the
	// arc is never coming, so the selection has to move off it.
	it('falls back when the catalogue lands without the craft in it', async () => {
		const panel = new TravelPanelState({
			...DEFAULT_TRIP,
			vehicleId: 'no-such-ship',
			profile: 'constant-thrust'
		});
		await panel.solve(EARTH, MARS, J2000);
		panel.acceptVehicles([ROCINANTE]);

		panel.updateTorch(EARTH, MARS, J2000);

		expect(panel.torch).toBeNull();
		expect(panel.selectedProfile).toBe('balanced');
	});

	// The two terms a URL cannot resolve on its own. Both are held as asked for
	// until the catalogue lands, and answered against it when it does.
	it('drops a craft the catalogue turns out not to have', async () => {
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, vehicleId: 'no-such-ship' });
		await panel.solve(EARTH, MARS, J2000);
		// Still asked for while nobody can say otherwise — the link is not wrong yet.
		expect(panel.vehicleId).toBe('no-such-ship');
		expect(panel.craftKnown).toBe(false);

		panel.acceptVehicles([ROCINANTE]);

		expect(panel.vehicleId).toBeNull();
		expect(panel.craftKnown).toBe(true);
	});

	// A catalogue that never arrives has to settle too, or every question about
	// the craft stays open for the rest of the session.
	it('settles on an empty catalogue rather than waiting forever', () => {
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, vehicleId: 'rocinante' });
		expect(panel.craftKnown).toBe(false);
		panel.acceptVehicles([]);
		expect(panel.craftKnown).toBe(true);
	});

	// The picker is the case the arc is meant to take over.
	it('selects the arc when a craft is chosen rather than restored', async () => {
		const panel = new TravelPanelState();
		panel.acceptVehicles([ROCINANTE]);
		await panel.solve(EARTH, MARS, J2000);
		panel.selectVehicle('rocinante');

		panel.updateTorch(EARTH, MARS, J2000);

		expect(panel.selectedProfile).toBe('constant-thrust');
	});
});

describe('TravelPanelState trip terms', () => {
	it('opens on the terms it was handed', () => {
		const trip = {
			...DEFAULT_TRIP,
			originMode: 'low-orbit' as const,
			targetMode: 'flyby' as const,
			timeMode: 'depart' as const,
			pickedJd: J2000 + 100,
			vehicleId: 'starship',
			passengers: 3,
			payloadKg: 800
		};
		expect(new TravelPanelState(trip).trip).toEqual(trip);
	});

	it('reports what the panel has been set to', () => {
		const panel = new TravelPanelState();
		panel.targetMode = 'elliptical';
		panel.payloadKg = 250;
		expect(panel.trip).toMatchObject({ targetMode: 'elliptical', payloadKg: 250 });
	});

	// Which end is a named place comes from the path, so it is not a term the
	// panel can be handed — and taking terms must not clear it.
	it('leaves the feature flags to the route', () => {
		const panel = new TravelPanelState();
		panel.targetIsFeature = true;
		panel.applyTrip({ ...DEFAULT_TRIP, targetMode: 'flyby' });
		expect(panel.targetIsFeature).toBe(true);
		expect(panel.arrivalMode).toBe('landing');
	});
});

describe('TravelPanelState craft off a shared link', () => {
	const CLIPPER = {
		id: 'europa-clipper',
		kind: 'probe',
		status: 'active',
		departsFrom: ['orbit']
	} as unknown as Vehicle;

	// The catalogue is fetched, so it lands after the panel has already been
	// handed the id. Reading it off the module instead left `vehicle` answering
	// null for good, and the craft looked lost on every shared link.
	it('resolves the craft once the catalogue lands', () => {
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, vehicleId: 'europa-clipper' });
		expect(panel.vehicle).toBeNull();

		panel.vehicles = [CLIPPER];

		expect(panel.vehicle).toBe(CLIPPER);
		// The id was never in doubt — it must stay in the URL through the wait.
		expect(panel.trip.vehicleId).toBe('europa-clipper');
	});

	it('keeps the id in the trip while the catalogue is still out', () => {
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, vehicleId: 'starship' });
		expect(panel.trip.vehicleId).toBe('starship');
	});
});

describe('TravelPanelState pick off a shared link', () => {
	// There is no grid to price against until the first solve lands, so the pick
	// has to survive the wait — and stay in the URL while it does, or the link
	// would erase its own pick on the way in.
	it('holds a pick until a solve can price it', async () => {
		const pick = { departJd: J2000 + 40, tofDays: 260 };
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, profile: 'custom', pick });

		expect(panel.custom).toBeNull();
		expect(panel.trip.pick).toEqual(pick);

		await panel.solve(EARTH, MARS, J2000);

		expect(panel.custom?.departJd).toBeCloseTo(pick.departJd, 6);
		expect(panel.custom?.tofDays).toBeCloseTo(pick.tofDays, 6);
		expect(panel.selectedProfile).toBe('custom');
	});

	it('drops a pick the solved field cannot place', async () => {
		const panel = new TravelPanelState({
			...DEFAULT_TRIP,
			profile: 'custom',
			pick: { departJd: J2000 + 50_000, tofDays: 3 }
		});

		await panel.solve(EARTH, MARS, J2000);

		expect(panel.custom).toBeNull();
		expect(panel.trip.pick).toBeNull();
		expect(panel.selectedProfile).not.toBe('custom');
	});
});

describe('TravelPanelState swing-by route', () => {
	const NOW = 2461080.5;

	/** A solved trip with whatever swing-by the search found standing beside it. */
	async function withAssist(): Promise<TravelPanelState> {
		const panel = new TravelPanelState();
		panel.targetMode = 'low-orbit';
		await panel.solve(EARTH, SATURN, NOW);
		await panel.updateAssist(EARTH, SATURN, [JUPITER], NOW);
		return panel;
	}

	it('goes past Jupiter for less than the direct routes cost', async () => {
		const panel = await withAssist();
		expect(panel.assist?.flybys?.[0].bodyId).toBe(JUPITER.id);
		const offered = panel.offered.find((choice) => choice.profile === 'gravity-assist');
		expect(offered).toBeDefined();
		expect(offered!.route.totalDvKms).toBeLessThan(
			Math.min(...panel.routes.map((choice) => choice.route.totalDvKms))
		);
	});

	// It sits after the three, being an alternative to them rather than one of
	// them, and before a hand-picked window, which is not the solver's at all.
	it('follows the solver’s own routes in the list', async () => {
		const panel = await withAssist();
		const profiles = panel.offered.map((choice) => choice.profile);
		expect(profiles.at(-1)).toBe('gravity-assist');
		expect(profiles.filter((p) => p !== 'gravity-assist')).toEqual(
			panel.routes.map((choice) => choice.profile)
		);
	});

	// Years of extra travel for the same price is not a choice worth offering.
	it('stays off the list when it only ties', async () => {
		const panel = await withAssist();
		panel.assist = { ...panel.assist!, totalDvKms: panel.routes[0].route.totalDvKms };
		expect(panel.offered.some((choice) => choice.profile === 'gravity-assist')).toBe(false);
	});

	// Unlike the constant-thrust arc: that is the answer a torch ship was chosen
	// for, while this lands a second late beside a list someone is already reading.
	it('never moves the selection on to itself', async () => {
		const panel = await withAssist();
		expect(panel.selectedProfile).not.toBe('gravity-assist');
	});

	it('falls back to a solved route when it is withdrawn', async () => {
		const panel = await withAssist();
		panel.selectedProfile = 'gravity-assist';
		panel.clearAssist();
		expect(panel.assist).toBeNull();
		expect(panel.selectedProfile).toBe('balanced');
	});

	// The hunt takes about a second and starting one stops the last, so a caller
	// that asked the same question twice a second would never get an answer.
	it('does not start the same hunt twice', async () => {
		const panel = await withAssist();
		const sentinel = { ...panel.assist!, totalDvKms: 999 };
		panel.assist = sentinel;
		await panel.updateAssist(EARTH, SATURN, [JUPITER], NOW);
		expect(panel.assist).toBe(sentinel);
	});

	it('hunts again once the trip is a different one', async () => {
		const panel = await withAssist();
		panel.assist = { ...panel.assist!, totalDvKms: 999 };
		// A flyby asks for a different arrival, so the answer is a different route.
		panel.targetMode = 'flyby';
		await panel.updateAssist(EARTH, SATURN, [JUPITER], NOW);
		expect(panel.assist!.totalDvKms).not.toBe(999);
		expect(panel.assist!.arrivalMode).toBe('flyby');
	});

	// Same shape as the pick and the craft off a shared link: the hunt is the
	// slowest answer on the panel, and everything landing in front of it used to
	// drop the trajectory the link was sent with.
	it('keeps a link’s choice while the hunt is still running', async () => {
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, profile: 'gravity-assist' });
		await panel.solve(EARTH, SATURN, NOW);
		expect(panel.trip.profile).toBe('gravity-assist');
		await panel.updateAssist(EARTH, SATURN, [JUPITER], NOW);
		expect(panel.selectedProfile).toBe('gravity-assist');
		expect(panel.selectedRoute?.flybys?.[0].bodyId).toBe(JUPITER.id);
	});

	// Going the long way round to Mars costs more than going straight there, so
	// the hunt answers with a route that is never offered — and the link that
	// asked for one has to let go of it rather than wait forever.
	it('lets the choice go once the hunt answers with nothing worth offering', async () => {
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, profile: 'gravity-assist' });
		await panel.solve(EARTH, MARS, NOW);
		await panel.updateAssist(EARTH, MARS, [JUPITER], NOW);
		expect(panel.offered.some((choice) => choice.profile === 'gravity-assist')).toBe(false);
		expect(panel.selectedProfile).toBe('balanced');
		expect(panel.trip.profile).toBe('balanced');
	});

	// The hunt is only ever compared against the direct routes, so it has to be
	// priced the way they are: a swing-by that paid full price for its capture
	// while they aerocaptured looks like one that saves nothing.
	it('prices its arrival the way the routes it is judged against are', async () => {
		const air = { ...SATURN, hasAtmosphere: true };
		const panel = new TravelPanelState();
		await panel.solve(EARTH, air, NOW);
		await panel.updateAssist(EARTH, air, [JUPITER], NOW);
		expect(panel.assist?.aero).toBe('aerocapture');
		expect(panel.offered.some((choice) => choice.profile === 'gravity-assist')).toBe(true);
	});

	// Aerocapture is the default, so this goes the other way: taking the air away
	// has to cost the swing-by its discount too.
	it('hunts again when the braking mode changes', async () => {
		const air = { ...SATURN, hasAtmosphere: true };
		const panel = new TravelPanelState();
		await panel.solve(EARTH, air, NOW);
		await panel.updateAssist(EARTH, air, [JUPITER], NOW);
		const aerocaptured = panel.assist!.totalDvKms;
		panel.aero = 'none';
		await panel.updateAssist(EARTH, air, [JUPITER], NOW);
		expect(panel.assist!.aero).toBe('none');
		expect(panel.assist!.totalDvKms).toBeGreaterThan(aerocaptured);
	});

	// The atmosphere arrives in a detail bundle, after the first hunt has already
	// answered — and it is worth ten kilometres per second at a giant. Keyed on
	// ids alone, the airless answer would stand for the rest of the session.
	it('hunts again once the destination turns out to have air', async () => {
		const dry = SATURN;
		const air = { ...SATURN, hasAtmosphere: true };
		const panel = new TravelPanelState();
		await panel.solve(EARTH, dry, NOW);
		await panel.updateAssist(EARTH, dry, [JUPITER], NOW);
		const airless = panel.assist!.totalDvKms;
		await panel.solve(EARTH, air, NOW);
		await panel.updateAssist(EARTH, air, [JUPITER], NOW);
		expect(panel.assist!.totalDvKms).toBeLessThan(airless);
		expect(panel.offered.some((choice) => choice.profile === 'gravity-assist')).toBe(true);
	});

	it('has nothing to offer before a search it can be compared against', () => {
		const panel = new TravelPanelState();
		panel.assist = buildAssistRoute(EARTH, JUPITER, SATURN, NOW, 900, 1400, {
			departureMode: 'orbit'
		});
		expect(panel.assist).not.toBeNull();
		expect(panel.offered).toEqual([]);
	});
});
