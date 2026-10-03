import * as m from '$lib/paraglide/messages.js';
import { formatDistance } from '$lib/format/distance';
import { AU_KM } from '$lib/math/units';
import type { MapText } from '$lib/systemmap/model';

/** The system map's own words, in the site's language and number formats. */
export function siteMapText(): MapText {
	return {
		primary: m.planetary_system_primary(),
		retrograde: m.planetary_system_retrograde(),
		moons: (count) => m.moons_count_moon({ count }),
		distance: (km) => formatDistance(km / AU_KM),
		axisAu: m.system_map_axis_au()
	};
}
