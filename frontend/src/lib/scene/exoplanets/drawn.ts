/**
 * Which planets of other stars draw. A planet draws only with a radius and a
 * surface map this embed may serve. The scene, the lineups, /compare and its
 * presets, and every compare button ask here, so a planet that one of them
 * leaves out is left out by all.
 */

import { loadTextureCredits } from '$lib/credits/texture-credits';
import { planetOfObjectId } from '$lib/fetch/extrasolar/ids';
import { planetCatalogue, type Planet, type PlanetCatalogue } from '$lib/fetch/extrasolar/planets';
import { JUPITER_RADIUS_KM } from '$lib/math/units';
import { drawsSurfaceMap } from '$lib/scene/objects/body/system';

type Catalogue = Pick<PlanetCatalogue, 'planet'>;

/** The planet's radius in km, an estimate too. NaN where the record has none. */
export function planetRadiusKm(planet: Planet): number {
	const radius = planet.values.radius;
	return typeof radius === 'number' && radius > 0 ? radius * JUPITER_RADIUS_KM : NaN;
}

/** Whether the planet `id` with the record `planet` draws. */
export function planetDraws(id: string, planet: Planet): boolean {
	return planetRadiusKm(planet) > 0 && drawsSurfaceMap(id, planet);
}

/** The record of the planet `id` when it draws, else null. Null for an id
 *  that is not a planet of another star, and for a record that fails to load. */
export async function drawnPlanet(
	id: string,
	catalogue: Catalogue = planetCatalogue
): Promise<Planet | null> {
	const at = planetOfObjectId(id);
	if (!at) return null;
	const planet = (await catalogue.planet(at.host, at.n).catch(() => null))?.planet;
	return planet && planetDraws(id, planet) ? planet : null;
}

/** Every planet that draws. The credits list each map, so only the planets
 *  they credit are read. */
export async function drawnPlanetIds(
	catalogue: Catalogue = planetCatalogue,
	credits: () => Promise<ReadonlyMap<string, unknown>> = loadTextureCredits
): Promise<ReadonlySet<string>> {
	const candidates = [...(await credits()).keys()].filter((id) => planetOfObjectId(id));
	const drawn = await Promise.all(candidates.map((id) => drawnPlanet(id, catalogue)));
	return new Set(candidates.filter((_, i) => drawn[i]));
}
