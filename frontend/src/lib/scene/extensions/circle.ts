/**
 * A circle round a place: a ring at some distance from a body, the reach of a
 * radio, the edge of a sphere of influence. It is a polygon whose outline is
 * worked out for the host, drawn in a plane it can turn wherever it likes.
 *
 * A ring is not filled unless the host asks for a fill, since the usual reason
 * to draw one round a body is to see the body inside it.
 */

import type { Anchor, OffsetKm } from './anchor';
import { circlePoints } from './geometry';
import { PolygonExtension } from './polygon';
import type { Shape, ShapeStyle } from './style';

export interface CircleOptions extends ShapeStyle {
	/** The middle of the circle. */
	anchor: Anchor;
	/** Distance from the anchor, in kilometres. */
	radiusKm: number;
	/** Which way the circle's plane faces, on ecliptic J2000 axes. The ecliptic
	 *  north pole when left out, which lays the ring in the plane the planets
	 *  go round in. A ring that has to turn with the body under it is a surface
	 *  circle instead. */
	normal?: OffsetKm;
	/** Points round the ring. More is rounder; the default is round enough to
	 *  fill the frame without corners. */
	steps?: number;
}

export interface Circle extends Shape {
	/** Draw it at another radius, in kilometres. */
	setRadiusKm(radiusKm: number): void;
}

export class CircleExtension extends PolygonExtension implements Circle {
	private readonly normal: OffsetKm | undefined;
	private readonly steps: number | undefined;

	constructor(options: CircleOptions) {
		const { radiusKm, normal, steps, ...style } = options;
		super({ ...style, points: circlePoints(radiusKm, { normal, steps }) });
		this.normal = normal;
		this.steps = steps;
	}

	setRadiusKm(radiusKm: number): void {
		this.setPoints(circlePoints(radiusKm, { normal: this.normal, steps: this.steps }));
	}
}
