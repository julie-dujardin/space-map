/**
 * What a chart draws of one figure of a sky culture: its lines, its stars, and
 * the named stars around it. Directions are unit vectors in ICRS axes, as the
 * Sun sees them.
 */

import {
	cultureStarName,
	unmatchedName,
	type SkyCultureFigure,
	type SkyCultureFile
} from '$lib/fetch/extrasolar/skycultures';
import { normalize, type Vec3 } from '$lib/math/travel/vec3';

export interface ChartStar {
	/** Extrasolar ID. */
	id: number;
	direction: Vec3;
	/** The name that the culture, or the international list, gives the star. */
	given?: string;
}

/** A member that is no star of the catalogue: a cluster, a nebula, a galaxy. */
export interface ChartStandIn {
	direction: Vec3;
	/** As the member list of the page names it. */
	name?: string;
}

export interface FigureChart {
	/** Every place of the figure: the frame holds them all. */
	points: Vec3[];
	lines: [Vec3, Vec3][];
	/** The stars of the figure. */
	stars: ChartStar[];
	standIns: ChartStandIn[];
	/** Named stars that are not of the figure. */
	neighbours: ChartStar[];
}

/** The named stars of a file with a place in the sky, by ID. */
function namedStars(file: SkyCultureFile, out: Map<number, ChartStar>): void {
	for (const { member, names } of file.names) {
		const { id, position } = file.members[member];
		const given = cultureStarName(names);
		if (id === undefined || !position || !given || out.has(id)) continue;
		out.set(id, { id, direction: normalize(position), given });
	}
}

/** Whether a member of the figure has a place in the sky, so a chart can draw it. */
export function figurePlaced(file: SkyCultureFile, figure: SkyCultureFigure): boolean {
	return [...figure.lines.flat(), ...(figure.group ?? [])].some(
		(index) => !!file.members[index].position
	);
}

/**
 * The chart of a figure. A line to a member with no position is left out. The
 * neighbours come from the star names of the culture, then from `others`: the
 * international names.
 */
export function figureChart(
	file: SkyCultureFile,
	figure: SkyCultureFigure,
	others: readonly SkyCultureFile[] = []
): FigureChart {
	const named = new Map<number, ChartStar>();
	namedStars(file, named);
	const directions = new Map<number, Vec3>();
	const direction = (index: number): Vec3 | undefined => {
		const position = file.members[index].position;
		if (!position) return undefined;
		let unit = directions.get(index);
		if (!unit) directions.set(index, (unit = normalize(position)));
		return unit;
	};
	const lines: [Vec3, Vec3][] = [];
	for (const chain of figure.lines) {
		for (let i = 1; i < chain.length; i++) {
			const a = direction(chain[i - 1]);
			const b = direction(chain[i]);
			if (a && b && chain[i - 1] !== chain[i]) lines.push([a, b]);
		}
	}
	for (const index of figure.group ?? []) direction(index);
	// A chain of one member draws no line, but the member is of the figure.
	for (const index of figure.lines.flat()) direction(index);
	const stars: ChartStar[] = [];
	const standIns: ChartStandIn[] = [];
	for (const [index, unit] of directions) {
		const member = file.members[index];
		if (member.id === undefined) standIns.push({ direction: unit, name: unmatchedName(member) });
		else stars.push({ id: member.id, direction: unit, given: named.get(member.id)?.given });
	}
	for (const other of others) namedStars(other, named);
	const own = new Set(stars.map(({ id }) => id));
	return {
		points: [...directions.values()],
		lines,
		stars,
		standIns,
		neighbours: [...named.values()].filter(({ id }) => !own.has(id))
	};
}
