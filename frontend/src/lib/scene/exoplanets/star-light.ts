/**
 * The star whose light the scene draws. The scene has one point light, the
 * Sun's. While the planets of another star draw as spheres, the light moves
 * to their host and takes its colour, so that they are lit from it. One light
 * keeps the light count of every shader, so no program compiles again.
 */

import { PointLight } from 'three';
import { SUN_ID } from '$lib/constants';
import { SUN_LIGHT_COLOUR } from '$lib/scene/lighting';
import { starLightColour } from '$lib/scene/starfield/colour';
import type { BodyObjects } from '$lib/scene/types';

export class StarLight {
	private light: PointLight | undefined;
	/** The body whose root holds the light. */
	starId = SUN_ID;

	/**
	 * Put the light on the root of `starId`, or on the Sun's while that star
	 * has no body with a place. Undefined until the Sun is built.
	 */
	seat(bodyObjects: Map<string, BodyObjects>, starId: string): PointLight | undefined {
		const sun = bodyObjects.get(SUN_ID);
		this.light ??= sun?.root.children.find((o): o is PointLight => o instanceof PointLight);
		if (!this.light || !sun) return undefined;
		const star = bodyObjects.get(starId);
		const holder = star?.body.position ? star : sun;
		if (this.light.parent === holder.root) return this.light;
		holder.root.add(this.light);
		this.starId = holder.body.data.id;
		const anchor = holder.body.extrasolar;
		this.light.color.setRGB(
			...(anchor ? starLightColour(anchor.teff, anchor.colour) : SUN_LIGHT_COLOUR)
		);
		return this.light;
	}
}
