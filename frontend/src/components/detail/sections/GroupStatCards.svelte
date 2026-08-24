<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import StatCardRow from './kit/StatCardRow.svelte';
	import type { Stat } from './kit/StatCard.svelte';
	import type { GlobalGroupData } from '$lib/fetch/groups/details';
	import {
		CAT_ASTEROIDS,
		CAT_COMETS,
		CAT_DEBRIS,
		CAT_DWARF_PLANETS,
		CAT_MOONS,
		CAT_PLANETS,
		CAT_PROBES,
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
	import {
		applyFeature,
		applyFocus,
		applyGroup,
		serializeUrl,
		urlTypeFromId
	} from '$lib/state/url';
	import { formatDistance } from '$lib/format/distance';
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
		formatUnit,
		joinParts
	} from '$lib/format/quantities';

	interface Props {
		global: GlobalGroupData | null;
	}
	let { global }: Props = $props();

	// Three across is what the row fits; a fourth squeezes every value. Each
	// family below names at most three, in slot order: how many, the extreme,
	// how it changes. A family with nothing for a slot leaves it empty rather
	// than reaching for a fact the charts and rows below already show.
	const MAX_CARDS = 3;
	// Mirrors the members strip: past this, the count rides its tab badge.
	const STRIP_CAPACITY = 5;
	// A hazardous share is a fraction of a percent — the bar would be a speck.

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');

	function focusBody(id: string, name: string, e: MouseEvent, tab?: 'rings' | 'structure') {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		// No focusObject in context — let the href do a full-page navigation.
		if (!focusObject) return;
		e.preventDefault();
		focusObject(id, name, { tab });
	}

	function openFeature(bodyId: string, featureId: number, name: string, e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!focusFeature) return;
		e.preventDefault();
		focusFeature(bodyId, featureId, name);
	}

	function focusGroup(slug: string, name: string, e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		e.preventDefault();
		appState.setGroup(slug, name);
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

	function count(label: string, n: number | undefined): Stat | null {
		if (!n) return null;
		return { label, value: formatNumber(n) };
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

	/** The member total, unless a strip or the tab badge already spells it out. */
	function members(g: GlobalGroupData, label: string): Stat | null {
		const notable = g.notable_members?.length ?? 0;
		if (notable > 0 && g.member_count > STRIP_CAPACITY) return null;
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
		return {
			label: m.group_stat_largest(),
			value: formatQuantity({ value: largest.diameter_km, unit: 'kilometre' }, true),
			tooltip: largest.name,
			href: serializeUrl(
				applyFocus(appState.view, {
					type: urlTypeFromId(bodyId),
					id: bodyId,
					name: largest.name
				})
			),
			onClick: (e) => focusBody(bodyId, largest.name, e)
		};
	}

	function widestRings(g: GlobalGroupData): Stat | null {
		const widest = g.widest_rings;
		if (!widest || !appState) return null;
		return {
			label: m.group_stat_widest(),
			// Compact, because the answer is millions of km wide and a card is a
			// third of the drawer.
			value: joinParts({
				value: formatCompactNumber(widest.span_km),
				unit: formatUnit('kilometre', true)
			}),
			tooltip: widest.name,
			href: serializeUrl(
				applyFocus(appState.view, {
					type: urlTypeFromId(widest.primary_id),
					id: widest.primary_id,
					name: widest.name,
					tab: 'rings'
				})
			),
			onClick: (e) => focusBody(widest.primary_id, widest.name, e, 'rings')
		};
	}

	/** The body a card points at, with the tab that shows what it is about. */
	function bodyCard(
		label: string,
		value: string,
		ref: { name: string; primary_id: string } | undefined,
		tab: 'structure'
	): Stat | null {
		if (!ref || !appState) return null;
		return {
			label,
			value,
			tooltip: ref.name,
			href: serializeUrl(
				applyFocus(appState.view, {
					type: urlTypeFromId(ref.primary_id),
					id: ref.primary_id,
					name: ref.name,
					tab
				})
			),
			onClick: (e) => focusBody(ref.primary_id, ref.name, e, tab)
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
		const erupting = g.erupting_now;
		if (!erupting?.length) return null;
		return {
			label: m.group_stat_erupting(),
			value: formatNumber(erupting.length),
			tooltip: erupting.join(', '),
			dot: 'bg-emerald-400'
		};
	}

	/** How much of the page anybody has actually measured. Three of seven, and
	 *  the tooltip names them because the answer is the surprise: the Moon, Mars
	 *  and Earth are the only places a dosimeter has been read out as a dose to
	 *  a body. Everything else here is a transport code. */
	function radiationMeasured(g: GlobalGroupData): Stat | null {
		const measured = g.radiation_measured;
		if (!measured?.length) return null;
		return {
			label: m.group_stat_radiation_measured(),
			value: formatNumber(measured.length),
			tooltip: measured.join(', ')
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
		return bodyCard(m.group_stat_most_tilted(), formatDegrees(tilted.degrees), tilted, 'structure');
	}

	function largestFeature(g: GlobalGroupData): Stat | null {
		const largest = g.largest_feature;
		if (!largest || !appState) return null;
		const bodyId = `${largest.primary_type}-${largest.primary_id}`;
		const featureId = parseInt(largest.secondary_id, 10);
		return {
			label: m.group_stat_largest(),
			value: formatQuantity({ value: largest.diameter_km, unit: 'kilometre' }, true),
			tooltip: largest.name,
			href: serializeUrl(
				applyFeature(appState.view, { bodyId, featureId, featureName: largest.name })
			),
			onClick: (e) => openFeature(bodyId, featureId, largest.name, e)
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
			href: serializeUrl(applyGroup(appState.view, pha.primary_id, label)),
			onClick: (e) => focusGroup(pha.primary_id, label, e)
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
			case CAT_ASTEROIDS:
				return [count(m.group_stat_named(), g.named_count), largestBody(g), hazardous(g)];
			case CAT_COMETS:
				return [largestBody(g), count(m.group_stat_split_families(), g.child_group_count)];
			case CAT_PLANETS:
			case CAT_DWARF_PLANETS:
				return [largestBody(g), count(m.group_stat_moons(), g.moon_total)];
			case CAT_MOONS:
				return [count(m.group_stat_hosts(), g.host_count), largestBody(g)];
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
				return [eruptingNow(g), hottestBody(g), count(m.group_stat_vents(), g.known_centres)];
			case CAT_TECTONICS:
				return [
					count(m.group_stat_styles(), g.tectonic_style_count),
					count(m.group_stat_moving(), g.tectonic_active_count)
				];
			case CAT_MAGNETIC_FIELDS:
				return [
					count(m.group_stat_dynamos(), g.dynamo_count),
					strongestField(g),
					mostTiltedField(g)
				];
			case CAT_TIDAL_HEATING:
				return [hottestBody(g), count(m.group_stat_tide_driven(), g.tide_dominant_count)];
			case CAT_RADIATION:
				return [radiationMeasured(g), quietestSurface(g)];
			case CAT_SATELLITES:
				return [active(g)];
			case CAT_DEBRIS:
				return [count(m.group_stat_sources(), g.child_group_count)];
			case CAT_PROBES:
				return [
					count(m.group_stat_missions(), g.child_group_count),
					year(m.group_stat_launched(), g.launch_year)
				];
			case CAT_SURFACE_FEATURES:
				return [
					members(g, m.group_stat_features()),
					largestFeature(g),
					count(m.group_stat_bodies(), g.body_count)
				];
			default:
				// The Solar System root: every number on it belongs to a child.
				return [];
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
				return [count(m.group_stat_named(), g.named_count), largestBody(g), hazardous(g)];
			case 'small_body_flag':
				return [
					members(g, m.group_stat_objects()),
					largestBody(g),
					distance(m.group_stat_moid(), g.median_moid_au, m.tooltip_group_stat_moid())
				];
			case 'feature_type':
				return [
					count(m.group_stat_bodies(), g.body_count),
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
		}
	}

	let stats = $derived.by<Stat[]>(() => {
		if (!global) return [];
		return statsFor(global)
			.filter((s): s is Stat => s != null)
			.slice(0, MAX_CARDS);
	});
</script>

<StatCardRow {stats} size="lg" />
