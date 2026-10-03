/**
 * Where the system map puts things: log distance × true relative diameter,
 * nudged vertically by inclination. The primary sits at the same scale with its
 * right limb pinned just left of the axis: a giant runs off the edge as a wall,
 * a Pluto-sized primary sits there as a whole disc.
 */

import type { MapBand, MapBody, MapSatellite, SystemMapModel } from './model';

export const VIEW_W = 720;
export const VIEW_H = 240;
export const X_LEFT = 44;
export const X_RIGHT = 700;
/** Baseline, raised to leave room for band labels. */
export const CY = 120;

/** Floor so small bodies stay visible dots. */
const MIN_R = 2.2;
const MAX_OFFSET = 84;
const PRIMARY_LIMB_X = X_LEFT - 4;

/** px between a body's top edge and its first satellite. */
const MOON_GAP = 4;
const MOON_SPACING = 3;

// Hit targets are padded well beyond the dots: the chart renders at ~0.4×, so
// a viewBox unit is a fraction of a device pixel.
export const HIT_MARGIN = 16;
/** Ranks any point inside a dot ahead of every point outside one. */
const INSIDE = 1e4;
const MOON_ZONE_W = 34;
const MOON_ZONE_PAD = 7;

/** ry/rx of a ringed body's apparent ring. */
export const RING_FORESHORTEN = 0.42;

export const BAND_Y = 26;
export const BAND_H = VIEW_H - 60;
/** Narrow bands would otherwise be a few device px of hit target. */
const BAND_MIN_HIT = 30;

export interface PlacedBody extends MapBody {
	cx: number;
	cy: number;
	r: number;
}

export interface PlacedSatellite extends MapSatellite {
	cx: number;
	cy: number;
	r: number;
	/** Its slice of the stack's zone, when it is a target of its own. */
	hitY: number;
	hitHeight: number;
}

export interface MoonZone {
	parent: PlacedBody;
	moons: PlacedSatellite[];
	x: number;
	y: number;
	width: number;
	height: number;
	/** Each moon is its own target rather than the stack being one. */
	perMoon: boolean;
}

export interface PlacedBand extends MapBand {
	x: number;
	width: number;
	/** Padded to BAND_MIN_HIT so a hairline band stays clickable. */
	hitX: number;
	hitWidth: number;
}

export interface Layout {
	bodies: PlacedBody[];
	moonZones: MoonZone[];
	bands: PlacedBand[];
	cloudPath: string;
	primaryR: number;
	primaryCx: number;
	xOf: (km: number) => number;
}

/** What the pointer or the keyboard is on. */
export type Hover =
	| { kind: 'primary' }
	| { kind: 'body'; id: string }
	| { kind: 'stack'; id: string }
	| { kind: 'moon'; parent: string; id: string }
	| { kind: 'band'; key: string };

export interface Tip {
	/** viewBox x the tooltip centers on. */
	cx: number;
	/** viewBox y the tooltip sits above. */
	cy: number;
	title: string;
	sub: string;
}

function minDistance(cx: number, cy: number, placed: PlacedBody[]): number {
	let min = Infinity;
	for (const p of placed) min = Math.min(min, Math.hypot(p.cx - cx, p.cy - cy));
	return min;
}

/** Retrograde orbits fold back from 180°, so the offset reads "tilt away from
 *  the plane" for both senses rather than running off the chart. */
function foldTilt(tiltDeg: number): number {
	return tiltDeg > 90 ? 180 - tiltDeg : tiltDeg;
}

export function layout(model: SystemMapModel): Layout {
	const logLo = Math.log10(model.domain[0]);
	const logSpan = Math.log10(model.domain[1]) - logLo;
	const xOf = (km: number) => {
		const t = (Math.log10(Math.max(km / model.unitKm, 1e-9)) - logLo) / logSpan;
		return X_LEFT + t * (X_RIGHT - X_LEFT);
	};

	// Inclination sets the vertical offset; its sign goes wherever there is more
	// room, so same-distance pairs and crowded swarms spread across the baseline
	// instead of stacking on it.
	const bodies: PlacedBody[] = [];
	for (const b of [...model.bodies].sort((a, b) => a.aKm - b.aKm)) {
		const cx = xOf(b.aKm);
		const r = Math.max(MIN_R, b.radiusKm * model.pxPerKm);
		let cy = CY;
		if (b.tiltDeg > 0) {
			const offset = Math.min(foldTilt(b.tiltDeg) * model.pxPerDeg, MAX_OFFSET);
			const up = CY - offset;
			const down = CY + offset;
			cy = minDistance(cx, up, bodies) >= minDistance(cx, down, bodies) ? up : down;
		}
		bodies.push({ ...b, cx, cy, r });
	}

	// Satellites stack straight up from their body, largest nearest it, above
	// its rings if any.
	const moonZones: MoonZone[] = [];
	for (const parent of bodies) {
		if (!parent.satellites?.length) continue;
		const ringTop = parent.rings ? parent.r * parent.rings.outer * RING_FORESHORTEN : 0;
		let y = parent.cy - Math.max(parent.r, ringTop) - MOON_GAP;
		const moons: PlacedSatellite[] = [];
		for (const s of [...parent.satellites].sort((a, b) => b.radiusKm - a.radiusKm)) {
			const r = Math.max(MIN_R, s.radiusKm * model.pxPerKm);
			y -= r;
			moons.push({ ...s, cx: parent.cx, cy: y, r, hitY: 0, hitHeight: 0 });
			y -= r + MOON_SPACING;
		}
		const top = Math.min(...moons.map((mn) => mn.cy - mn.r)) - MOON_ZONE_PAD;
		const bottom = Math.max(...moons.map((mn) => mn.cy + mn.r)) + MOON_ZONE_PAD;
		// Moons run bottom to top; each takes the zone up to halfway to its neighbours.
		moons.forEach((mn, idx) => {
			const below = idx === 0 ? bottom : (moons[idx - 1].cy + mn.cy) / 2;
			const above = idx === moons.length - 1 ? top : (moons[idx + 1].cy + mn.cy) / 2;
			mn.hitY = above;
			mn.hitHeight = below - above;
		});
		moonZones.push({
			parent,
			moons,
			x: parent.cx - MOON_ZONE_W / 2,
			y: top,
			width: MOON_ZONE_W,
			height: bottom - top,
			perMoon: !parent.grouped && !parent.satellitesLink && moons.some((mn) => mn.link)
		});
	}

	// Narrowest last: SVG paints in order, so the band hardest to hit ends up on
	// top of the wide ones its padded hit target overlaps.
	const bands = model.bands
		.map((b) => {
			const x = xOf(b.innerKm);
			const width = xOf(b.outerKm) - x;
			const hitWidth = Math.max(width, BAND_MIN_HIT);
			return { ...b, x, width, hitX: x + (width - hitWidth) / 2, hitWidth };
		})
		.sort((a, b) => b.width - a.width);

	// Inclination sets the offset as it does for bodies, its sign alternating so
	// the cloud straddles the baseline instead of stacking on one side. One path
	// of zero-length strokes: a dot per element would be a thousand DOM nodes.
	let cloudPath = '';
	model.cloud?.points.forEach((p, idx) => {
		const aUnits = p.aKm / model.unitKm;
		if (aUnits < model.domain[0] || aUnits > model.domain[1]) return;
		const offset = Math.min(Math.max(foldTilt(p.tiltDeg), 0) * model.pxPerDeg, MAX_OFFSET);
		const cy = CY + (idx % 2 === 0 ? -offset : offset);
		cloudPath += `M${xOf(p.aKm).toFixed(1)} ${cy.toFixed(1)}h0.01`;
	});

	const primaryR = model.primary.radiusKm * model.pxPerKm;
	return {
		bodies,
		moonZones,
		bands,
		cloudPath,
		primaryR,
		primaryCx: PRIMARY_LIMB_X - primaryR,
		xOf
	};
}

function inside(
	z: { x: number; y: number; width: number; height: number },
	vx: number,
	vy: number
) {
	return vx >= z.x && vx <= z.x + z.width && vy >= z.y && vy <= z.y + z.height;
}

/** The body nearest a viewBox point among those within `reach` of their
 *  edge, something to pick beating a landmark beside it. Within a dot its
 *  centre is what is aimed at: a small body drawn over a large one would
 *  otherwise never be the nearer of the two. */
function nearestBody(l: Layout, vx: number, vy: number, reach: number): PlacedBody | null {
	for (const pickable of [true, false]) {
		let nearest: PlacedBody | null = null;
		let gap = reach;
		for (const b of l.bodies) {
			if (!!b.link !== pickable) continue;
			const centre = Math.hypot(vx - b.cx, vy - b.cy);
			const edge = centre <= b.r ? centre - INSIDE : centre - b.r;
			if (edge > gap) continue;
			nearest = b;
			gap = edge;
		}
		if (nearest) return nearest;
	}
	return null;
}

/** What is under a viewBox point, front-most first: a body's own dot, then
 *  moon stacks, then the padding round the dots, then bands, then the
 *  primary. Where padded dots overlap the nearest one wins, so a crowded
 *  swarm stays pickable one body at a time. */
export function hitTest(l: Layout, vx: number, vy: number): Hover | null {
	const on = nearestBody(l, vx, vy, 0);
	if (on) return { kind: 'body', id: on.id };
	for (const z of l.moonZones) {
		if (!inside(z, vx, vy)) continue;
		if (z.parent.grouped) return { kind: 'body', id: z.parent.id };
		if (!z.perMoon) return { kind: 'stack', id: z.parent.id };
		const moon = z.moons.find((mn) => vy >= mn.hitY && vy <= mn.hitY + mn.hitHeight);
		if (moon) return { kind: 'moon', parent: z.parent.id, id: moon.id };
	}
	const near = nearestBody(l, vx, vy, HIT_MARGIN);
	if (near) return { kind: 'body', id: near.id };
	// Reversed for the same reason the bands are painted narrowest-last.
	for (let i = l.bands.length - 1; i >= 0; i--) {
		const band = l.bands[i];
		if (vx >= band.hitX && vx <= band.hitX + band.hitWidth && vy >= BAND_Y && vy <= BAND_Y + BAND_H)
			return { kind: 'band', key: band.key };
	}
	if (Math.hypot(vx - l.primaryCx, vy - CY) <= l.primaryR) return { kind: 'primary' };
	return null;
}

export function tipFor(model: SystemMapModel, l: Layout, hover: Hover | null): Tip | null {
	if (!hover) return null;
	const { text } = model;
	switch (hover.kind) {
		case 'primary':
			return {
				cx: Math.max(X_LEFT, l.primaryCx),
				cy: CY - Math.min(l.primaryR, CY - 40),
				title: model.primary.name,
				sub: text.primary
			};
		case 'body': {
			const b = l.bodies.find((p) => p.id === hover.id);
			if (!b) return null;
			const parts = [text.distance(b.aKm)];
			if (b.tiltDeg > 90) parts.push(text.retrograde);
			if (b.grouped && b.satellites?.length)
				parts.push(text.moons(b.satelliteCount ?? b.satellites.length));
			return { cx: b.cx, cy: b.cy - b.r - 4, title: b.name, sub: parts.join(' · ') };
		}
		case 'stack': {
			const zone = l.moonZones.find((z) => z.parent.id === hover.id);
			if (!zone) return null;
			const cx = zone.x + zone.width / 2;
			// Giants read as "Planet · N moons"; Earth's single Moon keeps its name.
			return zone.parent.satellitesTab
				? {
						cx,
						cy: zone.y,
						title: zone.parent.name,
						sub: text.moons(zone.parent.satelliteCount ?? zone.moons.length)
					}
				: { cx, cy: zone.y, title: zone.moons[0].name, sub: zone.parent.name };
		}
		case 'moon': {
			const zone = l.moonZones.find((z) => z.parent.id === hover.parent);
			const moon = zone?.moons.find((mn) => mn.id === hover.id);
			if (!zone || !moon) return null;
			return { cx: moon.cx, cy: moon.cy - moon.r - 4, title: moon.name, sub: zone.parent.name };
		}
		case 'band': {
			const band = l.bands.find((bd) => bd.key === hover.key);
			if (!band) return null;
			return {
				cx: band.x + band.width / 2,
				cy: 44,
				title: band.name ?? band.label,
				sub: band.sub ?? `${text.distance(band.innerKm)}–${text.distance(band.outerKm)}`
			};
		}
	}
}
