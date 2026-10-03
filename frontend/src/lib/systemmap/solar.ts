/**
 * The Solar System as a system map: Sun + planets + dwarfs on a fixed AU
 * domain, moons stacked on their planet, the belts as bands.
 */

import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
import { AU_KM } from '$lib/math/units';
import type {
	SolarSystemMapBelt,
	SolarSystemMapFile,
	SolarSystemMapObject
} from '$lib/fetch/groups/solar-system-map';
import type { MapBand, MapBody, MapLink, MapSatellite, MapText, SystemMapModel } from './model';

/** Radius px per km, tuned so Jupiter reads at ~16 px. Shared with the Sun,
 *  which genuinely dwarfs everything (≈156 px → mostly offscreen). */
export const SOLAR_PX_PER_KM = 2.24e-4;
export const SOLAR_PX_PER_DEG = 1.8;
/** AU; the Sun (a=0) is framed separately. */
const DOMAIN: [number, number] = [0.3, 50];
const TICKS = [0.3, 1, 3, 10, 30];
export const SUN_COLOR = '#ffdd44';

/** Strip a leading minor-planet designation ("50000 Quaoar" → "Quaoar") and
 *  tidy ALL-CAPS catalogue names. */
export function displayName(name: string): string {
	const stripped = name.replace(/^\d+\s+/, '');
	if (stripped === stripped.toUpperCase() && /[A-Z]/.test(stripped))
		return stripped.charAt(0) + stripped.slice(1).toLowerCase();
	return stripped;
}

export function solarColor(o: { id: string; color?: string | null }): string {
	return o.color || BODY_COLORS[o.id] || DEFAULT_BODY_COLOR;
}

/** A body's moons as the map stacks them, and what the stack stands for. */
export interface SolarStack {
	satellites: MapSatellite[];
	/** Every moon the body has; the stack's own length when absent. */
	count?: number;
	/** The stack stands for the whole system rather than its largest moon. */
	tab: boolean;
}

export interface SolarParts {
	text: MapText;
	name: (o: SolarSystemMapObject) => string;
	primaryLink?: MapLink;
	/** Objects worth drawing; every planet, dwarf and asteroid when absent. */
	keep?: (o: SolarSystemMapObject) => boolean;
	/** The stack over `o`; the file's own notable moons when absent. */
	stack?: (o: SolarSystemMapObject) => SolarStack | undefined;
	/** What the body and its stack lead to. */
	links: (
		o: SolarSystemMapObject,
		stack: SolarStack | undefined
	) => Pick<MapBody, 'link' | 'satellitesLink' | 'grouped'>;
	band: (belt: SolarSystemMapBelt) => Pick<MapBand, 'label' | 'sub' | 'href' | 'onclick'>;
}

/** The moons the file lists under each parent. */
export function fileStacks(
	file: SolarSystemMapFile,
	name: (o: SolarSystemMapObject) => string
): Map<string, SolarStack> {
	const stacks = new Map<string, SolarStack>();
	const planets = new Map(file.objects.map((o) => [o.id, o]));
	for (const o of file.objects) {
		if (o.kind !== 'moon' || !o.parent) continue;
		const stack = stacks.get(o.parent) ?? {
			satellites: [],
			count: planets.get(o.parent)?.moon_count,
			tab: false
		};
		stack.satellites.push({
			id: o.id,
			name: name(o),
			radiusKm: o.diameter_km / 2,
			color: solarColor(o)
		});
		stack.tab ||= !!o.link_parent;
		stacks.set(o.parent, stack);
	}
	return stacks;
}

export function solarSystemModel(
	file: SolarSystemMapFile,
	parts: SolarParts
): SystemMapModel | null {
	const sun = file.objects.find((o) => o.kind === 'star');
	if (!sun) return null;
	const listed = fileStacks(file, parts.name);
	const stackOf = parts.stack ?? ((o: SolarSystemMapObject) => listed.get(o.id));
	const bodies: MapBody[] = file.objects
		.filter((o) => o.kind !== 'moon' && o.kind !== 'star' && (parts.keep?.(o) ?? true))
		.map((o) => {
			const stack = stackOf(o);
			return {
				id: o.id,
				name: parts.name(o),
				aKm: o.a * AU_KM,
				tiltDeg: o.i,
				radiusKm: o.diameter_km / 2,
				color: solarColor(o),
				rings: o.rings,
				satellites: stack?.satellites,
				satelliteCount: stack?.count,
				satellitesTab: stack?.tab ?? false,
				...parts.links(o, stack)
			};
		});
	return {
		primary: {
			id: sun.id,
			name: parts.name(sun),
			radiusKm: sun.diameter_km / 2,
			color: SUN_COLOR,
			link: parts.primaryLink
		},
		bodies,
		bands: file.belts.map((b) => ({
			key: b.slug,
			innerKm: b.inner_au * AU_KM,
			outerKm: b.outer_au * AU_KM,
			tone: b.kind === 'kuiper_belt' ? 'sky' : 'muted',
			...parts.band(b)
		})),
		unitKm: AU_KM,
		domain: DOMAIN,
		ticks: TICKS,
		axisLabel: parts.text.axisAu,
		pxPerKm: SOLAR_PX_PER_KM,
		pxPerDeg: SOLAR_PX_PER_DEG,
		text: parts.text
	};
}
