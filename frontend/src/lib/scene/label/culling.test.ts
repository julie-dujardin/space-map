import { describe, expect, it } from 'vitest';
import { Object3D, PerspectiveCamera, Vector2 } from 'three';
import { ObjectType } from '$lib/types/objects';
import type { ContextManager } from '../state/context-manager.svelte';
import type { BodyObjects } from '../types';
import { cullOverlappingLabels } from './culling';

/** Which of two overlapping labels keeps its name in the cull. */

const CENTRE = 'x-1';
const STAR = 'x-11';

function bodyObjects(id: string, objectType: ObjectType, cachedDist: number): BodyObjects {
	const label = Object.assign(new Object3D(), { center: new Vector2(0.5, 0.5), visible: true });
	return {
		body: { data: { id, objectType }, position: [0, 0, -100] },
		label,
		labelHalo: null,
		labelStack: null,
		labelTextWidth: 50,
		cachedDist,
		isMinor: false
	} as unknown as BodyObjects;
}

function cull(
	focused: string | undefined,
	centres: [string, number][],
	starDist = 90
): BodyObjects[] {
	const centre = bodyObjects(CENTRE, ObjectType.EXTRASOLAR, 100);
	const star = bodyObjects(STAR, ObjectType.EXTRASOLAR, starDist);
	const camera = new PerspectiveCamera(60, 1, 0.1, 1000);
	camera.updateMatrixWorld();
	const ctx = {
		visibility: {
			isPinned: () => false,
			inFocus: (id: string) => id === focused,
			systemCentres: new Map(centres)
		}
	} as unknown as ContextManager;
	const bos = new Map([
		[CENTRE, centre],
		[STAR, star]
	]);
	cullOverlappingLabels(bos, 1000, 1000, camera, ctx, new Set(), []);
	return [centre, star];
}

describe('the labels of a star system', () => {
	it('keep the nearer star when neither is a centre', () => {
		const [centre, star] = cull(undefined, []);
		expect(star.labelMaximized).toBe(true);
		expect(centre.labelMaximized).toBe(false);
	});

	it('dim a nearer star that overlaps the centre of its system', () => {
		const [centre, star] = cull('naif-10', [[CENTRE, 1]]);
		expect(centre.labelMaximized).toBe(true);
		expect(star.labelMaximized).toBe(false);
	});

	it('keep a star that takes over the centre', () => {
		const [centre, star] = cull('naif-10', [[STAR, 1]], 110);
		expect(star.labelMaximized).toBe(true);
		expect(centre.labelMaximized).toBe(false);
	});

	it('dim the centre beside a focused star', () => {
		const [centre, star] = cull(STAR, [[CENTRE, 1]]);
		expect(star.labelMaximized).toBe(true);
		expect(centre.labelMaximized).toBe(false);
	});
});
