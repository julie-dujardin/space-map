/**
 * The Earth-orbit zones as bands on the Earth system map, and the satellite
 * catalogue as an anonymous cloud behind them.
 *
 * Only the zones a single radius defines survive the trip: the map's axis is
 * distance from the primary, while most of the classes (HEO, GTO, Molniya,
 * the graveyard, the inclination bands) are cut on the perigee-apogee plane
 * or on inclination and have no annulus of their own. Those keep the
 * scatter plot on their own pages, which plots what actually separates them.
 */

import * as m from '$lib/paraglide/messages.js';
import { formatKmRange } from '$lib/format/distance';
import {
	CLASS_SLUG_PREFIX,
	GEO_ALT_KM,
	R_EARTH_KM,
	orbitClassLabel,
	orbitClassShortLabel,
	type EarthOrbitSample
} from '$lib/charts/orbit-zones';
import type { MapBand, MapCloud } from './system-map';

/** The system map only draws these bands for Earth. */
export const EARTH_ID = 'naif-399';

/** Half-width of the geosynchronous band, matching `classifyEarthOrbit`. */
const GSO_HALF_WIDTH = 2000;
/** Cislunar cut — the outer edge of high Earth orbit. */
const HIGH_ALT_MAX = 500_000;

interface ZoneBand {
	/** Orbit class; names the `class-` page and labels the band. */
	className: string;
	/** Altitude span above the datum, in km. */
	from: number;
	to: number;
	tone: MapBand['tone'];
}

/** Inner to outer, tones alternating so neighbours read as two bands rather
 *  than one. High Earth orbit reaches past the Moon, which draws over it —
 *  bands are the backdrop bodies are read against. */
const ZONE_BANDS: ZoneBand[] = [
	{ className: 'LEO', from: 0, to: 2000, tone: 'sky' },
	{ className: 'MEO', from: 2000, to: GEO_ALT_KM - GSO_HALF_WIDTH, tone: 'muted' },
	{
		className: 'GEO',
		from: GEO_ALT_KM - GSO_HALF_WIDTH,
		to: GEO_ALT_KM + GSO_HALF_WIDTH,
		tone: 'amber'
	},
	{ className: 'HIGH', from: GEO_ALT_KM + GSO_HALF_WIDTH, to: HIGH_ALT_MAX, tone: 'muted' }
];

export interface EarthOrbitBand extends MapBand {
	/** `class-<NAME>`, the page the band opens. */
	slug: string;
	/** The name that page carries, for the group the click sets. */
	groupLabel: string;
}

/** The four bands, without their links — the caller owns navigation. */
export function earthOrbitBands(): EarthOrbitBand[] {
	return ZONE_BANDS.map((z) => ({
		key: z.className,
		label: z.className,
		name: orbitClassShortLabel(z.className),
		slug: `${CLASS_SLUG_PREFIX}${z.className}`,
		groupLabel: orbitClassLabel(z.className),
		innerKm: R_EARTH_KM + z.from,
		outerKm: R_EARTH_KM + z.to,
		sub: m.system_map_band_altitude({ range: formatKmRange(z.from, z.to) }),
		tone: z.tone
	}));
}

/** Every catalogued Earth orbiter as one dot at its own semi-major axis. The
 *  export samples the catalogue, so this is the shape of the population rather
 *  than a census — which is why no dot carries a name or a link. */
export function earthOrbitCloud(samples: EarthOrbitSample[]): MapCloud {
	return {
		points: samples
			.filter((s) => s.perigee_km >= 50 && s.apogee_km >= 50)
			.map((s) => ({
				aKm: R_EARTH_KM + (s.perigee_km + s.apogee_km) / 2,
				tiltDeg: s.inclination_deg ?? 0
			})),
		color: '#bed4ec'
	};
}
