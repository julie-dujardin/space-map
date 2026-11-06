/**
 * The star whose light the scene draws. The scene has one point light, the
 * Sun's. While the planets of another star draw as spheres, the light moves
 * to their host and takes its colour, so that they are lit from it. One light
 * keeps the light count of every shader, so no program compiles again.
 */

import { Color, PointLight } from 'three';
import { SUN_ID } from '$lib/constants';
import { photosphereColour } from '$lib/scene/starfield/colour';
import type { BodyObjects } from '$lib/scene/types';

export class StarLight {
	private light: PointLight | undefined;
	/** The Sun's own colour, put back when the light returns to it. */
	private readonly sunColour = new Color();
	/** The body whose root holds the light. */
	starId = SUN_ID;

	/**
	 * Put the light on the root of `starId`, or on the Sun's while that star
	 * has no body with a place. Undefined until the Sun is built.
	 */
	seat(bodyObjects: Map<string, BodyObjects>, starId: string): PointLight | undefined {
		const sun = bodyObjects.get(SUN_ID);
		if (!this.light) {
			this.light = sun?.root.children.find((o): o is PointLight => o instanceof PointLight);
			if (this.light) this.sunColour.copy(this.light.color);
		}
		if (!this.light || !sun) return undefined;
		const star = bodyObjects.get(starId);
		const holder = star?.body.position ? star : sun;
		if (this.light.parent === holder.root) return this.light;
		holder.root.add(this.light);
		this.starId = holder.body.data.id;
		const anchor = holder.body.extrasolar;
		// The colour the starfield draws the star's photosphere in.
		if (anchor) this.light.color.setRGB(...photosphereColour(anchor.teff, anchor.colour));
		else this.light.color.copy(this.sunColour);
		return this.light;
	}
}
