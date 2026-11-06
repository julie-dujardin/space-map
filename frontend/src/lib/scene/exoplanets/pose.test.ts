import { Object3D, Vector3 } from 'three';
import { describe, expect, it } from 'vitest';
import { posePlanet } from './pose';
import { orbitNormal } from './view';

/** A planet with no spin model keeps its north on its orbit normal and
 *  longitude 0 on its star, or on its node. */

const ORBIT = { i: 30, om: 40 };
const local = (obj: Object3D, x: number, y: number, z: number) =>
	new Vector3(x, y, z).applyQuaternion(obj.quaternion);

describe('posePlanet', () => {
	it('turns a locked planet to its star', () => {
		const obj = new Object3D();
		const normal = new Vector3(...orbitNormal(ORBIT.i, ORBIT.om));
		// A star in the plane of the orbit, and one off it by a little.
		const inPlane = new Vector3(1, 0, 0).projectOnPlane(normal).normalize();
		const host = inPlane.clone().addScaledVector(normal, 0.01);
		posePlanet(obj, ORBIT, { tidally_locked: true }, [0, 0, 0], [host.x, host.y, host.z]);
		expect(local(obj, 0, 1, 0).distanceTo(normal)).toBeLessThan(1e-9);
		expect(local(obj, 1, 0, 0).distanceTo(inPlane)).toBeLessThan(1e-9);
	});

	it('keeps any other planet on the ascending node', () => {
		for (const tidally_locked of [false, null]) {
			const obj = new Object3D();
			posePlanet(obj, ORBIT, { tidally_locked }, [0, 0, 0], [5, 1, 2]);
			const node = new Vector3(Math.cos((40 * Math.PI) / 180), 0, -Math.sin((40 * Math.PI) / 180));
			expect(local(obj, 1, 0, 0).distanceTo(node)).toBeLessThan(1e-9);
			expect(local(obj, 0, 1, 0).dot(node)).toBeCloseTo(0, 12);
		}
	});
});
