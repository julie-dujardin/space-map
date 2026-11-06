/**
 * What an artist's impression of a planet of another star rests on, as its
 * record gives it: the measured values, not the catalogue's estimates or
 * limits. The impression warning lists them.
 */

import type { Planet, PlanetHost } from '$lib/fetch/extrasolar/planets';
import { getLocale } from '$lib/host';
import * as m from '$lib/paraglide/messages.js';

export type ImpressionFact = 'size' | 'mass' | 'molecules' | 'distance' | 'brightness';

const FACT_TEXT: Record<ImpressionFact, () => string> = {
	size: m.artist_impression_fact_size,
	mass: m.artist_impression_fact_mass,
	molecules: m.artist_impression_fact_molecules,
	distance: m.artist_impression_fact_distance,
	brightness: m.artist_impression_fact_brightness
};

/** The facts of `planet` in the order the warning lists them. A minimum mass
 *  counts as a mass. The brightness of the star needs its temperature and
 *  radius, as the host record has no luminosity. */
export function impressionFacts(
	planet: Pick<Planet, 'values' | 'estimated' | 'limits'>,
	host: Pick<PlanetHost, 'teff' | 'radius'> | undefined
): ImpressionFact[] {
	const { values } = planet;
	const estimated = new Set(planet.estimated);
	// A limit is its key and a sign: `mass<`.
	const limited = new Set(planet.limits.map((limit) => limit.slice(0, -1)));
	const measured = (key: string) => typeof values[key] === 'number' && !estimated.has(key);
	const molecules = values.molecules;
	const facts: ImpressionFact[] = [];
	if (measured('radius')) facts.push('size');
	if (measured('mass') && !limited.has('mass')) facts.push('mass');
	if (Array.isArray(molecules) && molecules.length > 0) facts.push('molecules');
	if (measured('semi_major_axis')) facts.push('distance');
	if (host?.teff && host.radius) facts.push('brightness');
	return facts;
}

/** The body of the warning, with the facts as a list of the reader's language. */
export function impressionText(facts: readonly ImpressionFact[]): string {
	if (facts.length === 0) return m.artist_impression_body_plain();
	const list = new Intl.ListFormat(getLocale(), { type: 'conjunction' });
	return m.artist_impression_body({ facts: list.format(facts.map((fact) => FACT_TEXT[fact]())) });
}
