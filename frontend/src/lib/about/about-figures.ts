/** The figures the /about page quotes, from the payload of /about/data. */

import type { AboutData, ObjectKind } from './data-payload';

export interface AboutFigures {
	generatedAt: string;
	/** Objects of the solar system, without the surface features. */
	objects: number;
	planets: number;
	dwarfPlanets: number;
	/** Moons of planets, dwarf planets and small bodies. */
	moons: number;
	asteroids: number;
	comets: number;
	spacecraft: number;
	debris: number;
	surfaceFeatures: number;
	texturedMoons: number;
	texturedMinorBodies: number;
	/** Bodies with a shape model, from a mission or from light curves. */
	shapedBodies: number;
	craftModels: number;
	colouredBodies: number;
	images: number;
	descriptions: number;
}

/** The planets are the 8 of the planet kind that SPICE positions; the others
 *  are exoplanets. */
const NAIF = 'naif';

const PLANET_ID = /^naif-[1-8]99$/;
const MOON_ID = /^naif-[1-9]\d\d$/;

function kindOf(data: AboutData, id: string): ObjectKind | undefined {
	return data.objects.find((kind) => kind.id === id);
}

function count(data: AboutData, id: string): number {
	return kindOf(data, id)?.count ?? 0;
}

function fromSource(kind: ObjectKind | undefined, key: string): number {
	return kind?.sources.find((source) => source.key === key)?.objects ?? 0;
}

function fromSourceInAll(data: AboutData, key: string): number {
	return data.objects.reduce((sum, kind) => sum + fromSource(kind, key), 0);
}

export function aboutFigures(data: AboutData): AboutFigures {
	const planets = fromSource(kindOf(data, 'planet'), NAIF);
	const solar = ['dwarf_planet', 'moon', 'asteroid', 'comet', 'satellite', 'probe', 'debris'];
	const worlds = data.systems.flatMap((system) => system.worlds).map((world) => world.id);
	const texturedMoons = worlds.filter((id) => MOON_ID.test(id) && !id.endsWith('99')).length;
	const texturedPlanets = worlds.filter((id) => PLANET_ID.test(id)).length;
	return {
		generatedAt: data.generated_at,
		objects: planets + solar.reduce((sum, id) => sum + count(data, id), 0),
		planets,
		dwarfPlanets: count(data, 'dwarf_planet'),
		moons: count(data, 'moon'),
		asteroids: count(data, 'asteroid'),
		comets: count(data, 'comet'),
		spacecraft: count(data, 'satellite') + count(data, 'probe'),
		debris: count(data, 'debris'),
		surfaceFeatures: count(data, 'surface_feature'),
		texturedMoons,
		texturedMinorBodies: worlds.length - texturedMoons - texturedPlanets,
		shapedBodies: data.models.worlds.length + (data.models.lightcurve?.worlds ?? 0),
		// The comparables are the reference objects of the compare page.
		craftModels: data.models.craft
			.filter((group) => group.kind !== 'comparable')
			.reduce((sum, group) => sum + group.models.length, 0),
		colouredBodies: fromSourceInAll(data, 'truecolortools'),
		images: fromSourceInAll(data, 'commons'),
		descriptions: fromSourceInAll(data, 'wikipedia')
	};
}

/** The README's style: 987, 4k, 16k, 1.6m. Rounded down, so a figure is never
 *  more than the data holds. */
export function shortCount(n: number): string {
	if (n < 1000) return String(n);
	const [unit, suffix] = n >= 1e6 ? [1e6, 'm'] : [1e3, 'k'];
	const value = n / unit;
	return `${value < 10 ? Math.floor(value * 10) / 10 : Math.floor(value)}${suffix}`;
}

/** For "over N": rounded down to the tens. */
export function roundCount(n: number): number {
	return n < 10 ? n : Math.floor(n / 10) * 10;
}
