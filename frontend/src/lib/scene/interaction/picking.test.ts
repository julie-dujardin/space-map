import { describe, expect, it } from 'vitest';
import { PerspectiveCamera, Vector2, Vector3 } from 'three';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { pickSystemDot, type DotPick } from './picking';

/** A click near a planet of another star, or near its host, takes the nearer one. */

const HOST = 'x-27424668';

function body(id: string, objectType: ObjectType, at: [number, number, number]): PositionedBody {
	return { data: { id, objectType, parentId: HOST }, position: at } as unknown as PositionedBody;
}

function pick(pointerNdc: [number, number], shares: Map<string, number>, starShare = 1): DotPick {
	const host = body(HOST, ObjectType.EXTRASOLAR, [0, 0, -10]);
	const planets = [
		body('x-27424668-b-1', ObjectType.EXOPLANET, [0.5, 0, -10]),
		body('x-27424668-b-2', ObjectType.EXOPLANET, [-3, 0, -10])
	];
	const all = new Map([host, ...planets].map((b) => [b.data.id, b]));
	const ctx = {
		getBody: (id: string) => all.get(id),
		place: (b: PositionedBody) => b.position,
		exoplanets: { held: () => ({ planets: new Map([[27424668, planets]]) }) },
		visibility: {
			systemShares: shares,
			starShare,
			exoplanetShare: (b: PositionedBody) => shares.get(b.data.parentId) ?? 0
		}
	} as unknown as ContextManager;
	const camera = new PerspectiveCamera(60, 1, 0.01, 1000);
	camera.updateMatrixWorld();
	return {
		pointer: new Vector2(...pointerNdc),
		camera,
		ctx,
		focusTruePos: [0, 0, 0],
		canvasWidth: 1000,
		canvasHeight: 1000,
		tmpV3: new Vector3(),
		jd: 2451545,
		pointerType: 'mouse'
	};
}

describe('pickSystemDot', () => {
	const shares = new Map([[HOST, 1]]);
	// One scene unit at 10 units away is about 87 px on a 1000 px view.
	const ndcOf = (x: number) => [x / 10 / Math.tan(Math.PI / 6), 0] as [number, number];

	it('takes the dot nearest the pointer: a planet, or its host', () => {
		expect(pickSystemDot(pick(ndcOf(0.45), shares))?.body.data.id).toBe('x-27424668-b-1');
		expect(pickSystemDot(pick(ndcOf(0.05), shares))?.body.data.id).toBe(HOST);
		expect(pickSystemDot(pick(ndcOf(-2.9), shares))?.body.data.id).toBe('x-27424668-b-2');
	});

	it('takes nothing out of the pick radius, or where no system draws', () => {
		expect(pickSystemDot(pick(ndcOf(1.5), shares))).toBeNull();
		expect(pickSystemDot(pick(ndcOf(0.45), new Map()))).toBeNull();
	});

	it('leaves the host to the starfield while the stars do not draw', () => {
		expect(pickSystemDot(pick(ndcOf(0), shares))?.body.data.id).toBe(HOST);
		expect(pickSystemDot(pick(ndcOf(0), shares, 0))).toBeNull();
	});
});
