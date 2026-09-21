/**
 * Launch vehicles the row can stand side by side. A rocket is no Object in
 * the catalogue — nothing orbits as one — so each is a standalone model
 * bundle reached by its slug, and named here. One model per rocket: the
 * bundles hold several of some, and the row wants each vehicle once.
 *
 * What the catalogue does know is the family: the launch-vehicle group the
 * satellite catalogue files launches under. That is the page a rocket opens.
 */

import { resolve } from '$app/paths';
import * as m from '$lib/paraglide/messages.js';
import { fetchModelIndex } from '$lib/fetch/models';
import type { LineupBody } from '../../components/detail/charts/BodyLineup.svelte';
import { craftWidthRatio } from '../../components/detail/charts/lineup-fit';

export interface Rocket {
	/** Model bundle slug; also the id the row draws it under. */
	slug: string;
	label: () => string;
	/** The launch-vehicle group this is one member of — Falcon 9 and Falcon
	 *  Heavy share one. Absent where the catalogue files no launches under it. */
	group?: string;
}

export const ROCKETS: Rocket[] = [
	{ slug: 'saturn-v', label: m.compare_rocket_saturn_v, group: 'lv-saturn' },
	{ slug: 'n1', label: m.compare_rocket_n1 },
	{ slug: 'space-shuttle', label: m.compare_rocket_space_shuttle, group: 'lv-space-shuttle' },
	{ slug: 'starship', label: m.compare_rocket_starship, group: 'lv-starship' },
	{ slug: 'new-glenn', label: m.compare_rocket_new_glenn, group: 'lv-new-glenn' },
	{ slug: 'falcon-heavy', label: m.compare_rocket_falcon_heavy, group: 'lv-falcon' },
	{ slug: 'falcon-9-block-5', label: m.compare_rocket_falcon_9, group: 'lv-falcon' },
	{ slug: 'vulcan-centaur', label: m.compare_rocket_vulcan_centaur, group: 'lv-vulcan' },
	{ slug: 'atlas-v', label: m.compare_rocket_atlas_v, group: 'lv-atlas' },
	{ slug: 'delta-ii', label: m.compare_rocket_delta_ii, group: 'lv-delta' },
	{ slug: 'ariane-5', label: m.compare_rocket_ariane_5, group: 'lv-ariane' },
	{ slug: 'ariane-6', label: m.compare_rocket_ariane_6, group: 'lv-ariane' },
	{ slug: 'vega-c', label: m.compare_rocket_vega_c, group: 'lv-vega' },
	{ slug: 'soyuz-fg', label: m.compare_rocket_soyuz_fg, group: 'lv-soyuz-rocket' },
	{ slug: 'proton-m', label: m.compare_rocket_proton_m, group: 'lv-proton-m' },
	{ slug: 'long-march-5', label: m.compare_rocket_long_march_5, group: 'lv-long-march' },
	{ slug: 'h-iia', label: m.compare_rocket_h_iia, group: 'lv-h-2' },
	{ slug: 'epsilon', label: m.compare_rocket_epsilon, group: 'lv-epsilon' },
	{ slug: 'm-v', label: m.compare_rocket_m_v, group: 'lv-mu-rocket' },
	{ slug: 'pslv', label: m.compare_rocket_pslv, group: 'lv-pslv' },
	{ slug: 'lvm3', label: m.compare_rocket_lvm3, group: 'lv-lvm3' },
	{ slug: 'electron', label: m.compare_rocket_electron, group: 'lv-electron' },
	{ slug: 'neutron', label: m.compare_rocket_neutron },
	{ slug: 'terran-1', label: m.compare_rocket_terran_1, group: 'lv-terran-1' },
	{ slug: 'firefly-alpha', label: m.compare_rocket_firefly_alpha, group: 'lv-firefly' },
	{ slug: 'astra-rocket-3', label: m.compare_rocket_astra_rocket_3, group: 'lv-astra-rocket-3' },
	{ slug: 'mercury-atlas', label: m.compare_rocket_mercury_atlas, group: 'lv-atlas' },
	{ slug: 'mercury-redstone', label: m.compare_rocket_mercury_redstone }
];

export function rocketBySlug(id: string): Rocket | undefined {
	return ROCKETS.find((r) => r.slug === id);
}

/** The members of one family, in the list's order. */
export function rocketsOf(group: string): Rocket[] {
	return ROCKETS.filter((r) => r.group === group);
}

/** The whole rocket lineup on the compare page, opened on one of them. */
export function rocketsCompareHref(slug: string): string {
	return `${resolve('/compare')}?m=${ROCKETS.map((r) => r.slug).join(',')}&on=${slug}`;
}

/**
 * Row bodies for `rockets`, sized off their bundles: a rocket is all vehicle,
 * so the manifest span is its size whole, with none of it read as a boom.
 * `href` says where each links from the row — its family's page, or the
 * comparison — and null where it links nowhere. One with no measured bundle
 * is dropped: a rocket of unknown height has no place in a size comparison.
 */
export async function rocketBodies(
	rockets: readonly Rocket[],
	href: (rocket: Rocket) => string | null
): Promise<LineupBody[]> {
	const index = await fetchModelIndex().catch(() => null);
	if (!index) return [];
	const bodies: LineupBody[] = [];
	for (const rocket of rockets) {
		const entry = index.find((e) => e.slug === rocket.slug);
		if (!entry?.scale_meters) continue;
		bodies.push({
			id: rocket.slug,
			name: rocket.label(),
			radiusKm: entry.scale_meters / 2000,
			model: rocket.slug,
			craft: true,
			aspect: entry.span_ratios ? craftWidthRatio(entry.span_ratios) || undefined : undefined,
			href: href(rocket)
		});
	}
	return bodies;
}
