<script lang="ts">
	import { getContext } from 'svelte';
	import { sortNames } from '$lib/format/name';
	import * as m from '$lib/paraglide/messages.js';
	import StatCardRow from './kit/StatCardRow.svelte';
	import type { Stat, StatSize } from './kit/StatCard.svelte';
	import type { GlobalGroupData, LocalizedGroupData } from '$lib/fetch/groups/details';
	import {
		CAT_ASTEROIDS,
		CAT_COMETS,
		CAT_DEBRIS,
		CAT_DWARF_PLANETS,
		CAT_MOONS,
		CAT_PLANETS,
		CAT_CONSTELLATIONS,
		CAT_STARS,
		CAT_STAR_SYSTEMS,
		CAT_PLANETARY_SYSTEMS,
		CAT_PROBES,
		CAT_SPACECRAFT,
		CAT_RING_SYSTEMS,
		CAT_SATELLITES,
		CAT_SURFACE_FEATURES,
		CAT_ATMOSPHERES,
		CAT_OCEANS,
		CAT_VOLCANISM,
		CAT_TECTONICS,
		CAT_MAGNETIC_FIELDS,
		CAT_TIDAL_HEATING,
		CAT_RADIATION
	} from '$lib/fetch/groups/registry';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';
	import { applyFeature, serializeUrl } from '$lib/state/url';
	import { focusClick, focusHref, groupClick, groupHref } from '$lib/state/focus-link';
	import { isModifiedClick } from '$lib/modified-click';
	import { formatCompactKm, formatDistance } from '$lib/format/distance';
	import { SOLAR_RADIUS_KM } from '$lib/math/units';
	import { EARTH_RADIUS_KM } from '$lib/math/units';
	import { EARTH_ID } from '$lib/constants';
	import { earthOceans, oceanVolume } from '../charts/OceanVolumeChart.svelte';
	import { fieldParts, powerParts } from '$lib/format/activity';
	import { formatDoseRate } from '$lib/format/radiation';
	import {
		asPercent,
		formatCompactNumber,
		formatDegrees,
		formatNumber,
		formatQuantity,
		formatShare,
		formatUnit,
		earthRatio,
		joinParts
	} from '$lib/format/quantities';

	interface Props {
		global: GlobalGroupData | null;
		/** Names the bodies the cards point at in the reader's language. */
		localized: LocalizedGroupData | null;
		/** The tab of the Planets page these cards head; the overview without it. */
		tab?: 'solar-system' | 'exoplanets';
	}
	let { global, localized, tab }: Props = $props();

	// A row fits three cards. Four cards go in two rows of two. Each family
	// below names three at most, in this order: how many, the extreme, how it
	// changes. A family with nothing for a slot leaves the slot empty.
	const MAX_CARDS = 4;
	const ROW = 3;
	// A hazardous share is a fraction of a percent — the bar would be a speck.

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');

	function openFeature(bodyId: string, featureId: number, name: string, e: MouseEvent) {
		if (isModifiedClick(e) || !focusFeature) return;
		e.preventDefault();
		focusFeature(bodyId, featureId, name);
	}

	/** A body a card points at, by its name in the reader's language: the
	 *  bundle names the members of the page, and the bodies of its charts and
	 *  cards, by Object.id. */
	function bodyName(ref: { name: string; primary_id: string }): string {
		const id = ref.primary_id;
		return localized?.body_names?.[id] ?? localized?.notable_member_names?.[id] ?? ref.name;
	}

	/** The names of `refs` in the reader's language, in its alphabetical order:
	 *  the export sorts them by their global names. */
	function nameList(refs: { name: string; primary_id: string }[]): string {
		return sortNames(refs.map(bodyName)).join(', ');
	}

	function ofTotal(n: number, total: number): string | undefined {
		if (!total) return undefined;
		return m.group_stat_of_total({
			n: formatNumber(n),
			total: formatNumber(total),
			percent: formatNumber((n / total) * 100)
		});
	}

	function km(label: string, value: number | undefined): Stat | null {
		if (value == null) return null;
		return { label, value: formatQuantity({ value, unit: 'kilometre' }, true) };
	}

	function count(label: string, n: number | undefined, tooltip?: string): Stat | null {
		if (!n) return null;
		return { label, value: formatNumber(n), tooltip };
	}

	/** A star count: tens of millions do not fit a card in full, so the card
	 *  shows the compact figure and the tooltip the exact one. */
	function stars(label: string, n: number | undefined): Stat | null {
		if (!n) return null;
		if (n < 1e6) return { label, value: formatNumber(n) };
		return { label, value: formatCompactNumber(n), tooltip: formatNumber(n) };
	}

	/** The Stars page: the share of stars with a family, catalogued or estimated. */
	function classifiedShare(g: GlobalGroupData): Stat | null {
		const published = g.published_star_count ?? 0;
		const estimated = g.estimated_star_count ?? 0;
		if (!g.member_count || published + estimated === 0) return null;
		return {
			label: m.group_stat_classified(),
			value: formatShare((published + estimated) / g.member_count),
			tooltip: m.tooltip_star_classified({
				published: formatNumber(published),
				estimated: formatNumber(estimated)
			})
		};
	}

	/** As `largestPlanet`, against the Sun. */
	function largestStar(g: GlobalGroupData): Stat | null {
		const largest = g.largest_star;
		if (!largest || !appState) return null;
		return {
			label: m.group_stat_largest(),
			value: formatCompactKm(2 * largest.radius_sun * SOLAR_RADIUS_KM),
			tooltip: `${bodyName(largest)} — ${m.tooltip_star_vs_sun({ ratio: formatNumber(Math.round(largest.radius_sun)) })}`,
			...planetLink(largest)
		};
	}

	/** The share of a family's members that only an estimate puts there. */
	function estimatedShare(
		g: GlobalGroupData,
		estimated: number | undefined,
		label: string,
		tooltip: string
	): Stat | null {
		if (!g.member_count || !estimated) return null;
		return {
			label,
			value: formatShare(estimated / g.member_count),
			tooltip: `${formatNumber(estimated)} — ${tooltip}`
		};
	}

	/** Years are labels, not quantities — no thousands separator. */
	function year(label: string, y: number | undefined): Stat | null {
		if (!y) return null;
		return { label, value: String(y) };
	}

	/** AU down to ~1.5 M km, then kilometres — the app's distance convention. */
	function distance(label: string, valueAu: number | undefined, tooltip?: string): Stat | null {
		if (valueAu == null) return null;
		return { label, value: formatDistance(valueAu), tooltip };
	}

	/** The member total. This card is where a collection states how big it is —
	 *  the members tab carries no count badge, which crowded the bar. */
	function members(g: GlobalGroupData, label: string): Stat | null {
		return count(label, g.member_count);
	}

	function active(g: GlobalGroupData): Stat | null {
		if (!g.active_count) return null;
		return {
			label: m.group_stat_active(),
			value: formatNumber(g.active_count),
			tooltip: ofTotal(g.active_count, g.member_count),
			share: g.member_count ? g.active_count / g.member_count : undefined,
			dot: 'bg-emerald-400'
		};
	}

	function largestBody(g: GlobalGroupData): Stat | null {
		const largest = g.largest_body;
		if (!largest || !appState) return null;
		// `object` ids are whole already; SBDB ones carry the bare spkid.
		const bodyId =
			largest.primary_type === 'object'
				? largest.primary_id
				: `${largest.primary_type}-${largest.primary_id}`;
		const name = bodyName({ name: largest.name, primary_id: bodyId });
		return {
			label: m.group_stat_largest(),
			value: formatQuantity({ value: largest.diameter_km, unit: 'kilometre' }, true),
			tooltip: name,
			href: focusHref(appState, bodyId, name),
			onClick: focusClick(focusObject, bodyId, name)
		};
	}

	/** A planet's page, from a card about it. */
	function planetLink(ref: { primary_id: string; name: string }) {
		const name = bodyName(ref);
		return {
			href: focusHref(appState, ref.primary_id, name),
			onClick: focusClick(focusObject, ref.primary_id, name)
		};
	}

	/** The largest radius as a diameter in kilometres, as the site gives sizes. */
	function largestPlanet(g: GlobalGroupData): Stat | null {
		const largest = g.largest_planet;
		if (!largest || !appState) return null;
		const vsEarth = earthRatio(largest.radius_earth);
		return {
			label: m.group_stat_largest(),
			value: formatQuantity(
				{ value: 2 * largest.radius_earth * EARTH_RADIUS_KM, unit: 'kilometre' },
				true
			),
			tooltip: vsEarth ? `${bodyName(largest)} — ${vsEarth}` : bodyName(largest),
			...planetLink(largest)
		};
	}

	function firstExoplanet(g: GlobalGroupData): Stat | null {
		const first = g.first_exoplanet;
		if (!first || !appState) return null;
		return {
			label: m.group_stat_first_found(),
			value: String(first.discovery_year),
			tooltip: bodyName(first),
			...planetLink(first)
		};
	}

	/** The system a card counts for, and its page. */
	function topSystem(
		label: string,
		ref: { primary_id: string; name: string } | undefined,
		n: number | undefined
	): Stat | null {
		if (!ref || n == null || !appState) return null;
		return { label, value: formatNumber(n), tooltip: bodyName(ref), ...planetLink(ref) };
	}

	/** The Planets page: every planet on the overview, then a card set per tab. */
	function planetsStats(g: GlobalGroupData): (Stat | null)[] {
		if (tab === 'solar-system') return [largestBody(g), count(m.group_stat_moons(), g.moon_total)];
		if (tab === 'exoplanets')
			return [count(m.group_stat_exoplanets(), g.exoplanet_count), firstExoplanet(g)];
		return [
			members(g, m.group_stat_planets()),
			count(m.group_stat_families(), g.planet_family_count),
			largestPlanet(g)
		];
	}

	function widestRings(g: GlobalGroupData): Stat | null {
		const widest = g.widest_rings;
		if (!widest || !appState) return null;
		const name = bodyName(widest);
		return {
			label: m.group_stat_widest(),
			// Compact, because the answer is millions of km wide and a card is a
			// third of the drawer.
			value: formatCompactKm(widest.span_km),
			tooltip: `${m.tooltip_group_stat_widest()} — ${name}`,
			href: focusHref(appState, widest.primary_id, name, 'rings'),
			onClick: focusClick(focusObject, widest.primary_id, name, { tab: 'rings' })
		};
	}

	/** The body a card points at, with the tab that shows what it is about. */
	function bodyCard(
		label: string,
		value: string,
		ref: { name: string; primary_id: string } | undefined,
		tab: 'structure',
		/** What a terse label stands for, ahead of the body's name. */
		lead?: string
	): Stat | null {
		if (!ref || !appState) return null;
		const name = bodyName(ref);
		return {
			label,
			value,
			tooltip: lead ? `${lead} — ${name}` : name,
			href: focusHref(appState, ref.primary_id, name, tab),
			onClick: focusClick(focusObject, ref.primary_id, name, { tab })
		};
	}

	function tallestAtmosphere(g: GlobalGroupData): Stat | null {
		const tallest = g.tallest_atmosphere;
		if (!tallest) return null;
		return bodyCard(
			m.group_stat_tallest(),
			// Not compact: 4,000 km renders as "4K km", and a thousands suffix
			// beside a unit reads as kelvin.
			joinParts({ value: formatNumber(tallest.km), unit: formatUnit('kilometre', true) }),
			tallest,
			'structure'
		);
	}

	function deepestOcean(g: GlobalGroupData): Stat | null {
		const deepest = g.deepest_ocean;
		if (!deepest) return null;
		return bodyCard(
			m.group_stat_deepest(),
			joinParts({ value: formatNumber(deepest.thickness_km), unit: formatUnit('kilometre', true) }),
			deepest,
			'structure'
		);
	}

	/** Every ocean on the page added up — the one figure the chart below cannot
	 *  show, since a log axis has no sum. The multiple of Earth's is the finding,
	 *  but it is a comparison, so it hangs off the value as a tooltip. */
	function totalWater(g: GlobalGroupData): Stat | null {
		const total = g.ocean_volume_km3;
		const earth = g.notable_members?.find((e) => e.id === EARTH_ID)?.ocean?.volume_km3;
		if (!total) return null;
		return {
			label: m.group_stat_total_water(),
			value: oceanVolume(total),
			tooltip: earth ? (earthOceans(total / earth) ?? undefined) : undefined
		};
	}

	/** Caught in the act. The tooltip names them: four is few enough that a
	 *  reader wants to know which, and the number alone invites the question. */
	function eruptingNow(g: GlobalGroupData): Stat | null {
		const erupting = g.erupting_now_refs;
		if (!erupting?.length) return null;
		return {
			label: m.group_stat_erupting(),
			value: formatNumber(erupting.length),
			tooltip: nameList(erupting),
			dot: 'bg-emerald-400'
		};
	}

	/** How much of the page anybody has actually measured. Three of seven, and
	 *  the tooltip names them because the answer is the surprise: the Moon, Mars
	 *  and Earth are the only places a dosimeter has been read out as a dose to
	 *  a body. Everything else here is a transport code. */
	function radiationMeasured(g: GlobalGroupData): Stat | null {
		const measured = g.radiation_measured_refs;
		if (!measured?.length) return null;
		return {
			label: m.group_stat_radiation_measured(),
			value: formatNumber(measured.length),
			tooltip: nameList(measured)
		};
	}

	/** The chart cannot show this one: Venus is nine decades under the Moon, so
	 *  its bar is zero pixels and the card is where its figure reads. */
	function quietestSurface(g: GlobalGroupData): Stat | null {
		const quietest = g.quietest_surface;
		if (!quietest) return null;
		return bodyCard(
			m.group_stat_quietest(),
			formatDoseRate(quietest.sv_per_day),
			quietest,
			'structure'
		);
	}

	function hottestBody(g: GlobalGroupData): Stat | null {
		const hottest = g.hottest_body;
		if (!hottest) return null;
		const heat = powerParts(hottest.watts);
		return bodyCard(m.group_stat_hottest(), `${heat.value} ${heat.unit}`, hottest, 'structure');
	}

	function strongestField(g: GlobalGroupData): Stat | null {
		const strongest = g.strongest_field;
		if (!strongest) return null;
		const field = fieldParts(strongest.tesla);
		return bodyCard(
			m.group_stat_strongest(),
			`${field.value} ${field.unit}`,
			strongest,
			'structure'
		);
	}

	function mostTiltedField(g: GlobalGroupData): Stat | null {
		const tilted = g.most_tilted_field;
		if (!tilted) return null;
		return bodyCard(
			m.group_stat_most_tilted(),
			formatDegrees(tilted.degrees),
			tilted,
			'structure',
			m.tooltip_group_stat_most_tilted()
		);
	}

	function largestFeature(g: GlobalGroupData): Stat | null {
		const largest = g.largest_feature;
		if (!largest || !appState) return null;
		const bodyId = `${largest.primary_type}-${largest.primary_id}`;
		const featureId = parseInt(largest.secondary_id, 10);
		const name = localized?.largest_feature_name ?? largest.name;
		return {
			label: m.group_stat_largest(),
			value: formatQuantity({ value: largest.diameter_km, unit: 'kilometre' }, true),
			tooltip: name,
			href: serializeUrl(applyFeature(appState.view, { bodyId, featureId, featureName: name })),
			onClick: (e) => openFeature(bodyId, featureId, name, e)
		};
	}

	function hazardous(g: GlobalGroupData): Stat | null {
		if (!g.pha || !appState) return null;
		const pha = g.pha;
		const label = m.group_stat_pha();
		return {
			label,
			value: formatNumber(pha.n),
			tooltip: ofTotal(pha.n, g.member_count),
			share: g.member_count ? pha.n / g.member_count : undefined,
			dot: 'bg-rose-400',
			href: groupHref(appState, pha.primary_id, label),
			onClick: groupClick(appState, pha.primary_id, label)
		};
	}

	function success(g: GlobalGroupData): Stat | null {
		if (!g.launch_count || g.success_count == null) return null;
		return {
			label: m.group_stat_success(),
			value: joinParts(asPercent(formatNumber((g.success_count / g.launch_count) * 100))),
			tooltip: m.group_stat_failures({ count: g.failure_count ?? 0 }),
			dot: 'bg-emerald-400'
		};
	}

	function missionStatus(g: GlobalGroupData): Stat | null {
		if (!g.mission_status) return null;
		const [value, dot] =
			g.mission_status === 'operating'
				? [m.group_status_operating(), 'bg-emerald-400']
				: g.mission_status === 'lost'
					? [m.group_status_lost(), 'bg-rose-400']
					: [m.group_status_ended(), undefined];
		return { label: m.group_stat_status(), value, dot };
	}

	function categoryStats(g: GlobalGroupData): (Stat | null)[] {
		switch (g.slug) {
			// The hazardous subset is a child chip on this page already; the
			// classes below it are not, so they keep their PHA card.
			case CAT_ASTEROIDS:
				return [
					members(g, m.group_stat_objects()),
					count(m.group_stat_named(), g.named_count),
					largestBody(g)
				];
			case CAT_COMETS:
				return [
					members(g, m.group_stat_objects()),
					largestBody(g),
					count(m.group_stat_split_families(), g.child_group_count)
				];
			case CAT_STARS:
				return [stars(m.group_stat_stars(), g.member_count), classifiedShare(g), largestStar(g)];
			case CAT_STAR_SYSTEMS:
				return [
					stars(m.group_stat_systems(), g.member_count),
					count(m.group_stat_multiple_stars(), g.multiple_star_system_count),
					topSystem(m.group_stat_most_stars(), g.most_stars_system, g.most_stars_system?.stars)
				];
			case CAT_PLANETARY_SYSTEMS:
				return [
					count(m.group_stat_systems(), g.member_count),
					count(m.group_stat_multi_planet(), g.multi_planet_system_count),
					topSystem(
						m.group_stat_most_planets(),
						g.most_planets_system,
						g.most_planets_system?.planets
					)
				];
			case CAT_CONSTELLATIONS:
				return [members(g, m.group_type_plural_sky_culture())];
			case CAT_PLANETS:
				return planetsStats(g);
			case CAT_DWARF_PLANETS:
				return [largestBody(g), count(m.group_stat_moons(), g.moon_total)];
			case CAT_MOONS:
				return [
					members(g, m.group_stat_objects()),
					count(m.group_stat_hosts(), g.host_count),
					largestBody(g)
				];
			// The tiles already count each system's rings and the chart plots
			// their masses; these three are what neither says.
			case CAT_RING_SYSTEMS:
				return [
					count(m.group_stat_features(), g.ring_feature_count),
					widestRings(g),
					year(m.group_stat_discovered(), g.discovery_year)
				];
			case CAT_ATMOSPHERES:
				return [count(m.group_stat_types(), g.atmosphere_type_count), tallestAtmosphere(g)];
			case CAT_OCEANS:
				return [totalWater(g), deepestOcean(g)];
			case CAT_VOLCANISM:
				return [
					eruptingNow(g),
					hottestBody(g),
					count(m.group_stat_vents(), g.known_centres, m.tooltip_group_stat_vents())
				];
			case CAT_TECTONICS:
				return [
					count(m.group_stat_styles(), g.tectonic_style_count),
					count(m.group_stat_moving(), g.tectonic_active_count, m.tooltip_group_stat_moving())
				];
			case CAT_MAGNETIC_FIELDS:
				return [
					count(m.group_stat_dynamos(), g.dynamo_count),
					strongestField(g),
					mostTiltedField(g)
				];
			case CAT_TIDAL_HEATING:
				return [
					hottestBody(g),
					count(
						m.group_stat_tide_driven(),
						g.tide_dominant_count,
						m.tooltip_group_stat_tide_driven()
					)
				];
			case CAT_RADIATION:
				return [radiationMeasured(g), quietestSurface(g)];
			case CAT_SATELLITES:
				return [members(g, m.group_stat_objects()), active(g)];
			case CAT_DEBRIS:
				return [
					members(g, m.group_stat_objects()),
					count(m.group_stat_sources(), g.child_group_count)
				];
			case CAT_PROBES:
				return [
					members(g, m.group_stat_craft()),
					count(m.group_stat_missions(), g.child_group_count),
					year(m.group_stat_launched(), g.launch_year)
				];
			case CAT_SPACECRAFT:
				return [members(g, m.group_stat_objects()), year(m.group_stat_launched(), g.launch_year)];
			case CAT_SURFACE_FEATURES:
				return [
					members(g, m.group_stat_features()),
					largestFeature(g),
					count(m.group_stat_bodies(), g.body_count)
				];
			default:
				// The Solar System root: every number on it belongs to a child,
				// except how many things there are altogether.
				return [members(g, m.group_stat_objects())];
		}
	}

	// Comet orbit classes fall out of the small-body row with the largest member
	// alone: they carry neither an IAU-named count nor a hazardous subset, and
	// the discovery span they could show is the timeline chart's own x-axis.
	function statsFor(g: GlobalGroupData): (Stat | null)[] {
		switch (g.type) {
			case 'constellation':
			case 'organization':
			case 'country':
			case 'bus':
			case 'launch_site':
				return [
					members(g, m.group_stat_objects()),
					active(g),
					count(m.group_stat_decayed(), g.decayed_count)
				];
			case 'earth_orbit_class':
				return [
					members(g, m.group_stat_objects()),
					active(g),
					km(m.group_stat_perigee(), g.median_perigee_km)
				];
			case 'launch_vehicle':
				return [
					count(m.group_stat_launches(), g.launch_count),
					count(m.group_stat_payloads(), g.payload_count),
					success(g)
				];
			case 'orbit_class':
				return [members(g, m.group_stat_objects()), largestBody(g), hazardous(g)];
			case 'small_body_flag':
				return [
					members(g, m.group_stat_objects()),
					largestBody(g),
					distance(m.group_stat_moid(), g.median_moid_au, m.tooltip_group_stat_moid())
				];
			case 'feature_type':
				return [
					members(g, m.group_stat_features()),
					largestFeature(g),
					km(m.group_stat_median_diameter(), g.median_diameter_km)
				];
			case 'mission':
				return [
					members(g, m.group_stat_craft()),
					year(m.group_stat_launched(), g.launch_year),
					missionStatus(g)
				];
			case 'split_comet':
				return [
					members(g, m.group_stat_fragments()),
					year(m.group_stat_discovered(), g.discovery_year),
					distance(m.group_stat_perihelion(), g.perihelion_au)
				];
			case 'category':
				return categoryStats(g);
			case 'star_family':
				return [
					stars(m.group_stat_stars(), g.member_count),
					estimatedShare(
						g,
						g.estimated_star_count,
						m.group_stat_estimated(),
						m.tooltip_group_stat_estimated()
					)
				];
			case 'planet_family':
				return [
					members(g, m.group_stat_planets()),
					estimatedShare(
						g,
						g.estimated_planet_count,
						m.group_stat_estimated_planets(),
						m.tooltip_group_stat_estimated_planets()
					)
				];
			case 'sky_constellation':
				return [stars(m.group_stat_stars(), g.member_count)];
			case 'sky_culture':
				return [count(m.group_stat_figures(), g.member_count)];
		}
	}

	let stats = $derived.by<Stat[]>(() => {
		if (!global) return [];
		return statsFor(global)
			.filter((s): s is Stat => s != null)
			.slice(0, MAX_CARDS);
	});
	let rows = $derived(stats.length > ROW ? [stats.slice(0, 2), stats.slice(2)] : [stats]);
	// A six-figure size and its unit do not fit a third of the drawer at lg.
	let size = $derived<StatSize>(global?.slug === CAT_PLANETS && !tab ? 'md' : 'lg');
</script>

{#if rows.length > 1}
	<div class="flex flex-col gap-2">
		{#each rows as row, i (i)}
			<StatCardRow stats={row} {size} />
		{/each}
	</div>
{:else}
	<StatCardRow {stats} {size} />
{/if}
