/**
 * The attitude of a planet of another star, which has no spin model. Its
 * north is the normal of its orbit. A tidally locked planet turns longitude 0,
 * the centre of its map, to its star at every date. Any other planet keeps
 * longitude 0 toward the ascending node of its orbit.
 */

import { Matrix4, Vector3, type Object3D } from 'three';
import type { Vec3 } from '$lib/scene/animation/math';
import type { Planet } from '$lib/fetch/extrasolar/planets';
import type { BodyData } from '$lib/types/objects';
import { orbitNormal } from './view';

const DEG = Math.PI / 180;
const _north = new Vector3();
const _zero = new Vector3();
const _third = new Vector3();
const _basis = new Matrix4();

/** Turn `obj` so that local +Y is the orbit normal and local +X is longitude
 *  0. The sphere's map puts longitude 0 on local +X. */
export function posePlanet(
	obj: Object3D,
	orbit: Pick<BodyData, 'i' | 'om'>,
	planet: Pick<Planet, 'tidally_locked'>,
	pos: Readonly<Vec3>,
	hostPos: Readonly<Vec3>
): void {
	const { i, om } = orbit;
	_north.set(...orbitNormal(i, om));
	if (planet.tidally_locked === true) {
		_zero.set(hostPos[0] - pos[0], hostPos[1] - pos[1], hostPos[2] - pos[2]);
		_zero.addScaledVector(_north, -_zero.dot(_north));
		if (_zero.lengthSq() < 1e-30) return;
		_zero.normalize();
	} else {
		// The ascending node, ecliptic (cos Ω, sin Ω, 0), in the scene's (x, z, −y).
		_zero.set(Math.cos(om * DEG), 0, -Math.sin(om * DEG));
	}
	_third.crossVectors(_zero, _north);
	obj.quaternion.setFromRotationMatrix(_basis.makeBasis(_zero, _north, _third));
}
