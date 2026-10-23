import { describe, expect, it } from 'vitest';
import { Matrix4, Vector3 } from 'three';
import {
	PC_SCENE,
	boxDistance,
	boxMagnitude,
	childCentre,
	icrsToTree,
	sceneToTree,
	treeMatrixElements,
	treeToScene
} from './tree';

describe('render tree geometry', () => {
	it('places child k on the + side of each axis whose bit is set', () => {
		expect(childCentre([0, 0, 0], 8, 0)).toEqual([-4, -4, -4]);
		expect(childCentre([0, 0, 0], 8, 1)).toEqual([4, -4, -4]);
		expect(childCentre([0, 0, 0], 8, 6)).toEqual([-4, 4, 4]);
		expect(childCentre([10, 0, 0], 8, 7)).toEqual([14, 4, 4]);
	});

	it('measures the distance to a box, 0 inside it', () => {
		expect(boxDistance([1, 1, 1], [0, 0, 0], 2)).toBe(0);
		expect(boxDistance([5, 0, 0], [0, 0, 0], 2)).toBe(3);
		expect(boxDistance([5, 6, 0], [0, 0, 0], 2)).toBe(5);
	});

	it('gives the magnitude of a box from its range', () => {
		expect(boxMagnitude(0, 10, 6.5)).toBe(-Infinity);
		expect(boxMagnitude(10, 10, 6.5)).toBeCloseTo(6.5, 12);
		expect(boxMagnitude(100, 10, 6.5)).toBeCloseTo(11.5, 12);
		expect(boxMagnitude(1, 0, 6.5)).toBe(Infinity);
	});
});

describe('tree frame', () => {
	it('has a parsec of 206,265 AU', () => {
		expect(PC_SCENE / 10).toBeCloseTo(206264.806, 3);
	});

	it('round-trips a scene position', () => {
		const p = treeToScene(1.5, -2.25, 3, { x: 0, y: 0, z: 0 });
		const back = sceneToTree(p.x, p.y, p.z);
		expect(back[0]).toBeCloseTo(1.5, 12);
		expect(back[1]).toBeCloseTo(-2.25, 12);
		expect(back[2]).toBeCloseTo(3, 12);
	});

	it('keeps the vernal equinox on scene +x and sends the celestial pole up', () => {
		const x = treeToScene(1, 0, 0, { x: 0, y: 0, z: 0 });
		expect([x.x, x.y, x.z]).toEqual([PC_SCENE, 0, -0]);
		const pole = treeToScene(0, 0, 1, { x: 0, y: 0, z: 0 });
		expect(pole.y / PC_SCENE).toBeCloseTo(Math.cos((23.4392911 * Math.PI) / 180), 12);
	});

	it('takes a record position to the tree', () => {
		const p = icrsToTree(90, 0, 2);
		expect(p[0]).toBeCloseTo(0, 12);
		expect(p[1]).toBeCloseTo(2, 12);
		expect(p[2]).toBeCloseTo(0, 12);
		expect(icrsToTree(0, 90, 1)[2]).toBeCloseTo(1, 12);
	});

	it('builds the matrix that shifts the tree by the focus', () => {
		const focus: [number, number, number] = [3, -4, 5];
		const m = new Matrix4().fromArray(treeMatrixElements(focus, []));
		const v = new Vector3(0.25, -1, 2).applyMatrix4(m);
		const want = treeToScene(0.25, -1, 2, { x: 0, y: 0, z: 0 });
		expect(v.x).toBeCloseTo(want.x - 3, 6);
		expect(v.y).toBeCloseTo(want.y + 4, 6);
		expect(v.z).toBeCloseTo(want.z - 5, 6);
	});
});
