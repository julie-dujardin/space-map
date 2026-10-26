/**
 * The dot of a planet of another star, at the centre of its halo. Nothing
 * lights these planets, so the dot is all of the body that draws.
 */

import {
	BufferGeometry,
	CanvasTexture,
	Float32BufferAttribute,
	Points,
	PointsMaterial
} from 'three';
import { POINT_CLOUD_RENDER_ORDER } from '$lib/scene/objects/pointcloud';

/** Diameter of the dot, device px. */
const DOT_PX = 4;

let disc: CanvasTexture | null = null;

/** A solid round dot, shared by every planet. */
function discTexture(): CanvasTexture {
	if (disc) return disc;
	const size = 32;
	const canvas = document.createElement('canvas');
	canvas.width = size;
	canvas.height = size;
	const ctx = canvas.getContext('2d')!;
	ctx.beginPath();
	ctx.arc(size / 2, size / 2, size / 2 - 1, 0, Math.PI * 2);
	ctx.fillStyle = '#ffffff';
	ctx.fill();
	disc = new CanvasTexture(canvas);
	return disc;
}

/** One point at the origin of the body's group, in the planet's colour. */
export function makePlanetDot(color: string): Points {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute([0, 0, 0], 3));
	const material = new PointsMaterial({
		map: discTexture(),
		color,
		size: DOT_PX,
		sizeAttenuation: false,
		transparent: true,
		depthTest: true,
		depthWrite: false
	});
	const dot = new Points(geometry, material);
	dot.frustumCulled = false;
	dot.renderOrder = POINT_CLOUD_RENDER_ORDER;
	dot.name = 'planet-dot';
	return dot;
}
