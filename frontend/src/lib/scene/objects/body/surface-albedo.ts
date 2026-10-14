/**
 * The brightness of the ground of a body with no surface map, and of a body as
 * the source of planetshine. Both come from its V-band geometric albedo: the
 * luminance of `color`, or `geometric_albedo` where a hex cannot hold it or
 * where the body has no colour (export/small_body_color.py).
 *
 * The scene shades the ground by the law of the body (`photometry.ts`). A disc
 * of material colour 1 has a geometric albedo of 2/3 under the Lambert law and
 * of 1 under the lunar part of the lunar-Lambert law. The material colour is
 * the albedo over that factor, so each law gives the measured albedo.
 *
 * A surface map keeps the brightness it is published at: one fixed exposure
 * cannot show albedos from 0.02 to 1.4.
 */

import { Color, type Texture } from 'three';
import { getAtmosphereParams } from '$lib/fetch/atmospheres';
import { lunarLambertWeight } from '../surface/photometry';
import { meanMapColor } from './texture-tint';

/** What the brightness of the ground of a body comes from. `BodyData` and a
 *  lineup body both carry it. */
export interface SurfaceSource {
	id: string;
	/** Measured colour, sRGB hex. */
	color?: string;
	/** V-band geometric albedo. Set where the hex of `color` cannot hold it,
	 *  and on planets, which have no colour. */
	geometricAlbedo?: number;
	/** Factor on the lunar weight of the ground, from a disk-resolved fit. */
	lunarWeightScale?: number;
}

/** Stand-in for a surface with no measured colour: about the mean of the
 *  surface maps. White would blow out under the sun. */
const UNKNOWN_SURFACE_COLOR = '#6b6b6b';

function luminance(c: Color): number {
	return 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
}

/**
 * Geometric albedo at phase 0 of a disc of material colour 1, under the law
 * that `photometry.ts` gives the body: 2/3 for the Lambert law of a body with
 * an atmosphere, `(2 + w) / 3` for the lunar-Lambert law of weight `w`.
 */
export function discAlbedoPerColour(airless: boolean, lunarWeightScale?: number): number {
	if (!airless) return 2 / 3;
	return (2 + lunarLambertWeight(0, lunarWeightScale ?? 1)) / 3;
}

const _hex = new Color();

/**
 * Linear luminance of the material colour that gives the body its geometric
 * albedo. Null for a body with no measured colour.
 */
export function surfaceAlbedoTarget(body: SurfaceSource): number | null {
	if (!body.color) return null;
	const albedo = body.geometricAlbedo ?? luminance(_hex.set(body.color));
	return albedo / discAlbedoPerColour(!getAtmosphereParams(body.id), body.lunarWeightScale);
}

/** Material colour of the sphere with no map: the measured hue at the
 *  target, else the stand-in. */
export function untexturedSurfaceColour(body: SurfaceSource, out = new Color()): Color {
	const target = surfaceAlbedoTarget(body);
	if (target === null) return out.set(UNKNOWN_SURFACE_COLOR);
	out.set(body.color!);
	return out.multiplyScalar(target / luminance(out));
}

/**
 * Albedo of the body as a source of planetshine, which treats it as a Lambert
 * sphere: 3/2 of the geometric albedo, so that the full disc has that albedo.
 * The hue is that of `color`, else of the mean of `map`. Null for a body with
 * no albedo.
 */
export function shinerAlbedo(body: SurfaceSource, map: Texture | null, out: Color): Color | null {
	if (body.color) out.set(body.color);
	else if (body.geometricAlbedo === undefined) return null;
	else {
		const mean = map && meanMapColor(map);
		if (mean) out.copy(mean);
		else out.setRGB(1, 1, 1);
	}
	const albedo = body.geometricAlbedo ?? luminance(out);
	return out.multiplyScalar((1.5 * albedo) / luminance(out));
}
