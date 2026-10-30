/**
 * The Hertzsprung–Russell diagram of the Stars page
 * (`groups/__star_plot__.json.gz`, docs/export-format/groups.md). Fetched
 * once, when the chart first shows.
 */

import { dataBase } from '$lib/fetch/data-base';
import { memoizedGzJson } from '$lib/fetch/gz';

export interface StarPlotPoint {
	id: string;
	bp_rp: number;
	abs_g: number;
}

/** One row per sampled star. */
export interface StarPlotFile {
	bp_rp: number[];
	abs_g: number[];
	/** An index into `stages`; null when the star has none of them. */
	stage: (number | null)[];
	/** Star families, without their `star-` prefix. */
	stages: string[];
	named: StarPlotPoint[];
}

export const fetchStarPlot = memoizedGzJson<StarPlotFile>(
	() => `${dataBase()}/v1/groups/__star_plot__.json.gz`,
	{ error: (res) => `Failed to fetch the star plot: ${res.status}` }
);
