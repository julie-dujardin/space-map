import { describe, it, expect } from 'vitest';
import { EARTH, J2000, MARS } from '$lib/math/travel/test-fixtures';
import { buildConstantThrustRoute } from '$lib/math/travel';
import { TravelPanelState } from './panel.svelte';

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
});
