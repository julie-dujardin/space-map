import { CLASS_SLUG_PREFIX, type ZonePoint } from './orbit-zones';

/** Plot value → px, as produced by d3's linear/log scales. */
type Scale = (v: number) => number;

/** Closed SVG path for a zone outline, in px. */
export function polyPath(poly: ZonePoint[], xScale: Scale, yScale: Scale): string {
	if (poly.length === 0) return '';
	return (
		poly
			.map((p, i) => `${i === 0 ? 'M' : 'L'}${xScale(p.x).toFixed(2)},${yScale(p.y).toFixed(2)}`)
			.join(' ') + 'Z'
	);
}

/** Point-in-polygon (ray cast) in screen px against a zone outline. */
export function pointInZone(
	px: number,
	py: number,
	poly: ZonePoint[],
	xScale: Scale,
	yScale: Scale
): boolean {
	let inside = false;
	for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
		const xi = xScale(poly[i].x);
		const yi = yScale(poly[i].y);
		const xj = xScale(poly[j].x);
		const yj = yScale(poly[j].y);
		if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
	}
	return inside;
}

/** Real population of a class, from the groups index counts. */
export function zonePopulation(
	populationBySlug: Record<string, number>,
	className: string
): number {
	return populationBySlug[`${CLASS_SLUG_PREFIX}${className}`] ?? 0;
}
