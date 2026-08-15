import { describe, it, expect } from 'vitest';
import { EARTH, J2000, JUPITER, MARS, SATURN } from '$lib/math/travel/test-fixtures';
import {
	arrivalCampaignDays,
	buildAssistRoute,
	buildConstantThrustRoute,
	routeEndJd,
	type Vehicle
} from '$lib/math/travel';
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
		panel.targetAtSite = true;
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
		panel.originAtSite = true;
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

	// Added to what is on offer rather than opened: picking is a drag across the
	// field, and every point it crosses would otherwise be opened on the way.
	it('prices a point read off the field and adds it to the list', async () => {
		const panel = await solved();
		const [depart, tof] = centre(panel);
		panel.pickCustom(depart, tof);

		expect(panel.selectedProfile).toBeNull();
		expect(panel.custom?.departJd).toBeCloseTo(depart, 6);
		expect(panel.custom?.tofDays).toBeCloseTo(tof, 6);
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

		expect(panel.offered.at(-1)?.profile).toBe('custom');
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
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, 3.27, { departureMode: 'orbit' })!;
		panel.torchPresets = [{ profile: 'constant-thrust', route }];
		return panel;
	}

	// They lead the list. The craft they are offered for cannot fly the others.
	it('leads the list, ahead of the solver\u2019s own', () => {
		const panel = torched();
		expect(panel.offered.map((choice) => choice.profile)).toEqual(['constant-thrust']);
		// Being the only trajectory on offer is still not being chosen.
		expect(panel.selectedRoute).toBeNull();
		panel.choose('constant-thrust');
		expect(panel.selectedRoute?.constantThrust).toBe(3.27);
	});

	it('offers nothing once the arc is withdrawn and no search has landed', () => {
		const panel = torched();
		panel.selectedProfile = 'constant-thrust';
		panel.torchPresets = [];
		expect(panel.offered).toEqual([]);
		expect(panel.selectedRoute).toBeNull();
	});

	// The coast is a trade, offered the way a launch window is. Each named point
	// is cheaper and slower than the last.
	it('offers the coast as named points, each cheaper and slower than the last', () => {
		const panel = new TravelPanelState();
		panel.acceptVehicles([ROCINANTE]);
		panel.selectVehicle('rocinante');
		panel.updateTorch(EARTH, MARS, J2000);

		const arcs = panel.torchPresets;
		expect(arcs.map((arc) => arc.profile)).toEqual([
			'constant-thrust',
			'constant-thrust-balanced',
			'constant-thrust-efficient'
		]);
		for (let i = 1; i < arcs.length; i++) {
			expect(arcs[i].route.totalDvKms).toBeLessThan(arcs[i - 1].route.totalDvKms);
			expect(arcs[i].route.tofDays).toBeGreaterThan(arcs[i - 1].route.tofDays);
		}
		// The fastest arc has no coast in it at all.
		expect(arcs[0].route.legs.some((leg) => leg.kind === 'cruise')).toBe(false);
	});

	// The slider's arc joins the list. It does not replace what the presets say,
	// even when it lands on one of them.
	it('adds the slider\u2019s own arc, wherever the slider is', () => {
		const panel = new TravelPanelState();
		panel.acceptVehicles([ROCINANTE]);
		panel.selectVehicle('rocinante');
		panel.updateTorch(EARTH, MARS, J2000);

		panel.coastFraction = 0.5;
		panel.updateTorchCustom(EARTH, MARS, J2000);
		expect(panel.torchCustom?.profile).toBe('constant-thrust-custom');
		expect(panel.offered.at(3)?.profile).toBe('constant-thrust-custom');

		// On a preset, it is that preset's crossing under another name.
		panel.coastFraction = 0.25;
		panel.updateTorchCustom(EARTH, MARS, J2000);
		const balanced = panel.torchPresets.find((arc) => arc.profile === 'constant-thrust-balanced');
		expect(panel.torchCustom?.route.tofDays).toBeCloseTo(balanced!.route.tofDays, 6);
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
		expect(panel.torchPresets).toEqual([]);

		panel.acceptVehicles([ROCINANTE]);
		panel.updateTorch(EARTH, MARS, J2000);

		expect(panel.torchPresets.length).toBeGreaterThan(0);
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

		expect(panel.torchPresets.length).toBeGreaterThan(0);
		expect(panel.selectedProfile).toBe('constant-thrust');
	});

	// A craft the catalogue has no entry for is a real answer, not a wait: the
	// arc is never coming, so the trajectory a link named is put back on the list.
	it('lets the arc go when the catalogue lands without the craft in it', async () => {
		const panel = new TravelPanelState({
			...DEFAULT_TRIP,
			vehicleId: 'no-such-ship',
			profile: 'constant-thrust'
		});
		await panel.solve(EARTH, MARS, J2000);
		panel.acceptVehicles([ROCINANTE]);

		panel.updateTorch(EARTH, MARS, J2000);

		expect(panel.torchPresets).toEqual([]);
		expect(panel.selectedProfile).toBeNull();
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

	// Choosing a torch ship is not choosing its arc: it can fly the coasting
	// routes too, and which of them to fly is the step this would skip.
	it('offers the arc when a craft is chosen without opening it', async () => {
		const panel = new TravelPanelState();
		panel.acceptVehicles([ROCINANTE]);
		await panel.solve(EARTH, MARS, J2000);
		panel.selectVehicle('rocinante');

		panel.updateTorch(EARTH, MARS, J2000);

		expect(panel.offered[0]?.profile).toBe('constant-thrust');
		expect(panel.selectedProfile).toBeNull();
	});
});

describe('TravelPanelState choosing a trajectory', () => {
	/** The panel's two steps: nothing chosen is the list, a choice is the detail. */
	it('chooses nothing on its own when a search lands', async () => {
		const panel = new TravelPanelState();
		await panel.solve(EARTH, MARS, J2000);

		expect(panel.offered.length).toBeGreaterThan(0);
		expect(panel.selectedProfile).toBeNull();
		expect(panel.selectedRoute).toBeNull();
		expect(panel.trip.profile).toBeNull();
	});

	it('reads the one it is given, and goes back to the list on request', async () => {
		const panel = new TravelPanelState();
		await panel.solve(EARTH, MARS, J2000);

		panel.choose('efficient');
		expect(panel.selected?.profile).toBe('efficient');
		expect(panel.selectedRoute).toBe(
			panel.routes.find((choice) => choice.profile === 'efficient')?.route
		);

		panel.clearSelection();
		expect(panel.selectedRoute).toBeNull();
	});

	// The trajectory being read is a term of the trip, so a link opens on it.
	it('carries the choice in the trip and opens on it again', async () => {
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, profile: 'fast' });
		await panel.solve(EARTH, MARS, J2000);

		expect(panel.trip.profile).toBe('fast');
		expect(panel.selected?.profile).toBe('fast');
	});
});

/**
 * An end that does not keep still is described by elements good only near the
 * date they were read at. The search answers with dates of its own, and these
 * are how it goes back and asks about those.
 */
describe('TravelPanelState refining a moving end', () => {
	/** Mars a quarter of a turn along, standing in for an end that was described
	 *  by the wrong elements the first time round. */
	const MOVED = { ...MARS, elements: { ...MARS.elements, ma: (MARS.elements.ma + 90) % 360 } };

	it('leaves a trip alone when neither end has anything to add', async () => {
		const panel = new TravelPanelState();
		const asked: [string, number][] = [];
		await panel.solve(EARTH, MARS, J2000, undefined, async (role, jd) => {
			asked.push([role, jd]);
			return null;
		});

		expect(panel.status).toBe('ready');
		// Each end once, at its own date: the origin as it leaves, the target as
		// the craft gets there.
		expect(asked.map(([role]) => role)).toEqual(['origin', 'target']);
		expect(asked[0][1]).toBeLessThan(asked[1][1]);
	});

	it('asks each end at the dates the last pass landed on', async () => {
		const panel = new TravelPanelState();
		const dates: number[] = [];
		await panel.solve(EARTH, MARS, J2000, undefined, async (role, jd) => {
			if (role !== 'target') return null;
			dates.push(jd);
			return MOVED;
		});

		expect(panel.status).toBe('ready');
		expect(dates.length).toBeGreaterThan(1);
		// The second pass is asked about the arrival the first one found, which the
		// moved target has changed.
		expect(dates[1]).not.toBe(dates[0]);
	});

	it('stops once a pass stops moving the answer', async () => {
		const panel = new TravelPanelState();
		let passes = 0;
		await panel.solve(EARTH, MARS, J2000, undefined, async (role) => {
			if (role === 'target') passes++;
			return MOVED;
		});

		// However far it is let run, a fixpoint ends it — and nothing here diverges.
		expect(passes).toBeLessThanOrEqual(4);
		expect(panel.routes.length).toBeGreaterThan(0);
	});
});

describe('TravelPanelState arrival deadline', () => {
	async function byJd(deadlineJd: number): Promise<TravelPanelState> {
		const panel = new TravelPanelState({
			...DEFAULT_TRIP,
			timeMode: 'arrive',
			pickedJd: deadlineJd
		});
		await panel.solve(EARTH, MARS, J2000);
		return panel;
	}

	it('offers only trajectories that arrive in time', async () => {
		const deadlineJd = J2000 + 300;
		const panel = await byJd(deadlineJd);

		expect(panel.status).toBe('ready');
		expect(panel.routes.length).toBeGreaterThan(1);
		for (const { route } of panel.routes) expect(route.arriveJd).toBeLessThanOrEqual(deadlineJd);
	});

	// The deadline moves which routes are searched for rather than deleting the
	// ones that miss, so the cheap end of the list is a route that arrives in time
	// and not the absence of one.
	it('costs less than the trips left standing by filtering the answer', async () => {
		const deadlineJd = J2000 + 300;
		const panel = await byJd(deadlineJd);
		const open = new TravelPanelState();
		await open.solve(EARTH, MARS, J2000);

		const cheapest = Math.min(...panel.routes.map((choice) => choice.route.totalDvKms));
		const survivors = open.routes.filter((choice) => choice.route.arriveJd <= deadlineJd);
		expect(cheapest).toBeLessThan(Math.min(...survivors.map((choice) => choice.route.totalDvKms)));
	});

	// Two different nothings: this pair has transfers, they are simply all slower
	// than the date asked for. The panel says so rather than "no route found".
	it('reports a deadline nothing can meet as its own answer', async () => {
		const panel = await byJd(J2000 + 50);

		expect(panel.status).toBe('empty');
		expect(panel.grid!.solvedCount).toBeGreaterThan(0);
		expect(panel.missedDeadline).toBe(true);
	});

	it('claims no deadline was missed when none was set', async () => {
		const panel = new TravelPanelState();
		await panel.solve(EARTH, MARS, J2000);
		expect(panel.missedDeadline).toBe(false);
	});

	// An aerobraking arrival is captured months before it is in the orbit that was
	// asked for, and nothing else happens while drag walks it down. A deadline the
	// crossing meets but the campaign runs past is a deadline the trip misses.
	describe('with a campaign flown after arrival', () => {
		async function aerobraked(deadlineJd: number): Promise<TravelPanelState> {
			const panel = new TravelPanelState({
				...DEFAULT_TRIP,
				aero: 'aerobraking',
				timeMode: 'arrive',
				pickedJd: deadlineJd
			});
			panel.targetMode = 'low-orbit';
			await panel.solve(EARTH, MARS, J2000);
			return panel;
		}

		it('counts the campaign against the deadline', async () => {
			const campaignDays = arrivalCampaignDays(MARS, 'low-orbit', 'aerobraking');
			expect(campaignDays).toBeGreaterThan(30);

			const deadlineJd = J2000 + 400;
			const panel = await aerobraked(deadlineJd);
			for (const { route } of panel.routes) {
				expect(routeEndJd(route)).toBeLessThanOrEqual(deadlineJd);
				// And the crossing itself ends a campaign's worth earlier.
				expect(route.arriveJd).toBeLessThanOrEqual(deadlineJd - campaignDays + 1e-6);
			}
			expect(panel.routes.length).toBeGreaterThan(0);
		});

		// The reported case: a 3-month crossing was offered against a deadline the
		// 5-month campaign after it could never meet.
		it('offers nothing when only the crossing fits', async () => {
			const crossing = 91;
			const panel = await aerobraked(J2000 + crossing + 20);

			expect(panel.routes).toEqual([]);
			expect(panel.missedDeadline).toBe(true);
		});

		// The choice is held while the destination changes, but pricing has to
		// follow the arrival at hand: a landing with the control reading "none"
		// must not be grown a months-long campaign the held value describes.
		it('drops the campaign the moment the arrival stops being a low orbit', async () => {
			const crossing = 91;
			const panel = await aerobraked(J2000 + crossing + 20);
			panel.targetMode = 'surface';
			expect(panel.effectiveAero).toBe('none');
			await panel.solve(EARTH, MARS, J2000);

			expect(panel.routes.length).toBeGreaterThan(0);
			// And back: returning to a low orbit gets the held choice back.
			panel.targetMode = 'low-orbit';
			expect(panel.effectiveAero).toBe('aerobraking');
		});
	});
});

describe('TravelPanelState spiral', () => {
	/** Dawn: the drive the impulsive routes exist to be refused by. */
	const DAWN = {
		id: 'dawn',
		kind: 'probe',
		propulsion: 'electric',
		status: 'retired',
		departsFrom: ['orbit'],
		dryMassKg: { value: 793, source: 'test' },
		propellantMassKg: { value: 425, source: 'test' },
		ispS: { value: 3100, source: 'test' },
		thrustN: { value: 0.092, source: 'test' },
		// Derived in the pipeline from the three above, and carried in the export.
		dvKms: 3100 * 9.80665 * Math.log(1218 / 793) * 1e-3
	} as unknown as Vehicle;

	async function chosen(): Promise<TravelPanelState> {
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, originMode: 'low-orbit' });
		panel.acceptVehicles([DAWN]);
		await panel.solve(EARTH, MARS, J2000);
		panel.selectVehicle('dawn');
		panel.updateSpiral(EARTH, MARS, J2000);
		return panel;
	}

	// The whole point of the row: the craft that can fly none of the three above
	// it has one of its own, and it is the one selected.
	it('leads the list once a craft that cannot burn is chosen', async () => {
		const panel = await chosen();
		expect(panel.offered[0].profile).toBe('low-thrust');
		// Leading the list is not being chosen: the drive is what a spiral is a fact
		// about, but which trajectory to fly is still the reader's to say.
		expect(panel.selectedProfile).toBeNull();
		panel.choose('low-thrust');
		expect(panel.selectedRoute?.lowThrust?.accelMs2).toBeCloseTo(0.092 / 1218, 12);
	});

	// The refusal that started all this stays a refusal on the routes it is about,
	// and stops being one on the route that is about this drive.
	it('judges the spiral on Δv where the Lambert arcs cannot be judged at all', async () => {
		const panel = await chosen();
		const spiral = panel.offered.find((choice) => choice.profile === 'low-thrust')!;
		const fast = panel.offered.find((choice) => choice.profile === 'fast')!;
		expect(panel.feasibility(fast.route)?.status).toBe('not-modelled');
		// Out of reach rather than unjudged: escaping low Earth orbit on the drive
		// alone costs more than Dawn ever carried, and that is an answer.
		expect(panel.feasibility(spiral.route)?.status).toBe('insufficient-dv');
	});

	it('withdraws the spiral with the craft', async () => {
		const panel = await chosen();
		panel.choose('low-thrust');
		panel.selectVehicle('dawn');
		panel.updateSpiral(EARTH, MARS, J2000);
		expect(panel.spiral).toBeNull();
		// The trajectory being read is gone, so the reader is back in front of the
		// ones that are left.
		expect(panel.selectedProfile).toBeNull();
	});

	// Same wait for the catalogue as the held arc: a pass taken before it lands
	// must not read as "this craft flies no spiral" and drop the link's own choice.
	it('keeps a spiral a trip arrived selecting, across the wait for the catalogue', async () => {
		const panel = new TravelPanelState({
			...DEFAULT_TRIP,
			originMode: 'low-orbit',
			vehicleId: 'dawn',
			profile: 'low-thrust'
		});
		await panel.solve(EARTH, MARS, J2000);
		panel.updateSpiral(EARTH, MARS, J2000);
		expect(panel.selectedProfile).toBe('low-thrust');

		panel.acceptVehicles([DAWN]);
		panel.updateSpiral(EARTH, MARS, J2000);

		expect(panel.spiral).not.toBeNull();
		expect(panel.selectedProfile).toBe('low-thrust');
	});

	// Nothing at 76 µm/s² leaves a pad, so the trip that starts on one has no
	// spiral to offer and the list is the solver's own again.
	it('offers none from a surface', async () => {
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, originMode: 'surface' });
		panel.acceptVehicles([DAWN]);
		await panel.solve(EARTH, MARS, J2000);
		panel.selectVehicle('dawn');
		// Choosing it moved the origin off the ground, since Dawn departs from
		// orbit; the trip that insists is the one with no spiral to offer.
		expect(panel.originMode).toBe('low-orbit');
		panel.originMode = 'surface';
		panel.updateSpiral(EARTH, MARS, J2000);
		expect(panel.spiral).toBeNull();
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
		panel.targetAtSite = true;
		panel.applyTrip({ ...DEFAULT_TRIP, targetMode: 'flyby' });
		expect(panel.targetAtSite).toBe(true);
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

	it('goes back to the list when it is withdrawn', async () => {
		const panel = await withAssist();
		panel.choose('gravity-assist');
		panel.clearAssist();
		expect(panel.assist).toBeNull();
		expect(panel.selectedProfile).toBeNull();
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
		expect(panel.selectedProfile).toBeNull();
		expect(panel.trip.profile).toBeNull();
	});

	// The hunt lands about a second after the routes it is listed beside, which
	// is long enough for the reader to have picked one of them — and a choice
	// made by hand outranks the one the link arrived asking for.
	it('lets a choice made during the hunt stand when the hunt lands', async () => {
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, profile: 'gravity-assist' });
		await panel.solve(EARTH, SATURN, NOW);
		panel.choose('fast');
		await panel.updateAssist(EARTH, SATURN, [JUPITER], NOW);
		expect(panel.selectedProfile).toBe('fast');
		expect(panel.trip.profile).toBe('fast');
	});

	it('lets stepping back to the list settle a link’s wait too', async () => {
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, profile: 'gravity-assist' });
		await panel.solve(EARTH, SATURN, NOW);
		panel.clearSelection();
		expect(panel.trip.profile).toBeNull();
	});

	// A pair with no candidates never hunts at all — nothing inside one system
	// does — so a link asking for a swing-by there has its answer the moment the
	// hunt is cleared, not never. Left pending, the trip would report a
	// gravity-assist nothing offers for the rest of the session, and the early
	// return waiting on it would block every later settle.
	it('lets a link’s choice go when the pair has nothing to hunt', async () => {
		const panel = new TravelPanelState({ ...DEFAULT_TRIP, profile: 'gravity-assist' });
		await panel.solve(EARTH, MARS, NOW);
		panel.clearAssist();
		expect(panel.trip.profile).toBeNull();
		expect(panel.selectedProfile).toBeNull();
	});

	// The hunt is only ever compared against the direct routes, so it has to be
	// priced the way they are: a swing-by that paid full price for its capture
	// while they aerocaptured looks like one that saves nothing.
	it('prices its arrival the way the routes it is judged against are', async () => {
		const air = SATURN;
		const panel = new TravelPanelState();
		await panel.solve(EARTH, air, NOW);
		await panel.updateAssist(EARTH, air, [JUPITER], NOW);
		expect(panel.assist?.aero).toBe('aerocapture');
		expect(panel.offered.some((choice) => choice.profile === 'gravity-assist')).toBe(true);
	});

	// Aerocapture is the default, so this goes the other way: taking the air away
	// has to cost the swing-by its discount too.
	it('hunts again when the braking mode changes', async () => {
		const air = SATURN;
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
		const dry = { ...SATURN, aeroPressurePa: undefined, aeroScaleHeightKm: undefined };
		const air = SATURN;
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
