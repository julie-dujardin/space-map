import { describe, it, expect } from 'vitest';
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
