/**
 * The values of every planet for the two charts of the Planets page
 * (`groups/__planet_plot__.json.gz`, docs/export-format/groups.md). Fetched
 * once, when the chart first shows.
 */

import { dataBase } from '$lib/fetch/data-base';
import { memoizedGzJson } from '$lib/fetch/gz';

/** 0 measured (a true mass), 1 minimum mass, 2 estimated; null with no value. */
export type PlanetPlotFlag = 0 | 1 | 2 | null;

/** One row per planet: the Solar System planets first, named in `solar`. */
export interface PlanetPlotFile {
	/** Earth masses. */
	mass: (number | null)[];
	mass_flag: PlanetPlotFlag[];
	/** Earth radii. */
	radius: (number | null)[];
	radius_flag: PlanetPlotFlag[];
	/** AU. */
	semi_major_axis: (number | null)[];
	semi_major_axis_flag: PlanetPlotFlag[];
	/** Object ids of the first rows. */
	solar: string[];
}

export const fetchPlanetPlot = memoizedGzJson<PlanetPlotFile>(
	() => `${dataBase()}/v1/groups/__planet_plot__.json.gz`,
	{ error: (res) => `Failed to fetch the planet plot: ${res.status}` }
);
