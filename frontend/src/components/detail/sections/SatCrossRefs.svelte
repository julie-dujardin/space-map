<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type {
		EntityRef,
		FragmentOf,
		GlobalObjectData,
		LocalizedObjectData
	} from '$lib/fetch/objects/object-data';
	import type { OrbitalElements, PositionedBody } from '$lib/types/objects';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import { focusClick, focusHref, isModifiedClick } from '$lib/state/focus-link';
	import {
		CLASS_SLUG_PREFIX,
		classifyEarthOrbit,
		orbitClassLabel,
		orbitClassShortLabel
	} from '$lib/charts/orbit-zones';
	import { LAGRANGE_CLASS_NAMES } from '$lib/math/orbit/lagrange';
	import { fetchEarthMembership } from '$lib/fetch/groups/membership';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import { pickImageUrl } from '$lib/fetch/objects/images';
	import CrossRefCard from './crossref/CrossRefCard.svelte';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		/** TLE-derived elements (for the orbit inclination band). */
		orbitElements?: OrbitalElements;
		/** Focused body — a probe's L-point chip keys off its id and source. */
		body?: PositionedBody;
	}
	let { global, localized, orbitElements, body }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	let celestrak = $derived(global?.celestrak);
	let orbitsEarth = $derived(celestrak?.orbit_center === 'earth');

	// Most-specific-first: named special orbits beat inclination bands beat
	// eccentric/high regimes beat generic altitude bands; highest-ranked wins.
	const ORBIT_CLASS_SPECIFICITY = [
		'GEO',
		'IGSO',
		'GSO',
		'GRA',
		'MOL',
		'TUN',
		'GTO',
		'SSO',
		'POL',
		'RET',
		'EQU',
		'HEO',
		'MEO',
		'VHEO',
		'HIGH',
		'CIS',
		'VLEO',
		'LEO'
	];

	function groupRef(name: string, slug: string): EntityRef {
		return { name, primary_type: 'group', primary_id: slug };
	}

	function fragmentRef(f: FragmentOf): EntityRef {
		return { name: f.name, primary_type: f.primary_type, primary_id: f.primary_id };
	}

	interface CrossRef {
		label: string;
		/** Compact text shown on the tile; ref.name carries the full name (title). */
		display: string;
		ref: EntityRef;
	}

	let orbitClassRef = $derived.by<CrossRef | null>(() => {
		if (!orbitsEarth) return null;
		const inc = orbitElements?.i ?? global?.orbit?.i;
		const classes = classifyEarthOrbit(celestrak?.perigee, celestrak?.apogee, inc);
		if (classes.length === 0) return null;
		const best = classes.reduce((a, b) => {
			const ia = ORBIT_CLASS_SPECIFICITY.indexOf(a);
			const ib = ORBIT_CLASS_SPECIFICITY.indexOf(b);
			if (ia === -1) return b;
			if (ib === -1) return a;
			return ia <= ib ? a : b;
		});
		// Short name on the tile; full name stays in the title + group nav.
		return {
			label: m.orbit(),
			display: orbitClassShortLabel(best),
			ref: groupRef(orbitClassLabel(best), `${CLASS_SLUG_PREFIX}${best}`)
		};
	});

	// Probe orbit class: the Sun–Earth L1/L2 zone whose membership lists this
	// probe — the same source as the zone page, so chip and page agree.
	// Mutually exclusive with the earth-sat orbit-class slot above.
	let lagrangeRef = $state<CrossRef | null>(null);
	$effect(() => {
		const id = body?.data.id;
		if (!id || body?.data.orbitalSource !== OrbitalSource.SPICE_PROBE) {
			lagrangeRef = null;
			return;
		}
		let stale = false;
		fetchEarthMembership().then((mem) => {
			if (stale) return;
			const point = [...LAGRANGE_CLASS_NAMES].find((c) =>
				mem[`${CLASS_SLUG_PREFIX}${c}`]?.includes(id)
			);
			lagrangeRef = point
				? {
						label: m.orbit(),
						display: orbitClassShortLabel(point),
						ref: groupRef(orbitClassLabel(point), `${CLASS_SLUG_PREFIX}${point}`)
					}
				: null;
		});
		return () => {
			stale = true;
		};
	});

	// What is carrying it. More specific than the mission it belongs to — and
	// the two would say nearly the same thing — so it outranks the affiliation.
	let carriedByRef = $derived.by<CrossRef | null>(() => {
		const carrier = global?.carried_by;
		if (!carrier) return null;
		return { label: m.carried_by(), display: carrier.name, ref: fragmentRef(carrier) };
	});

	// What the craft belongs to: its mission, else the constellation it flies in.
	let affiliationRef = $derived.by<CrossRef | null>(() => {
		const mission = global?.mission ?? global?.part_of_mission;
		if (mission) return { label: m.mission(), display: mission.name, ref: fragmentRef(mission) };
		const con = localized?.constellation;
		if (con) return { label: m.group_type_constellation(), display: con.name, ref: con };
		return null;
	});

	// What it is built on: the bus already names its own manufacturer, so the
	// two never both earn a tile. Arrays count only with one clear primary.
	let platformRef = $derived.by<CrossRef | null>(() => {
		const bus = localized?.bus;
		if (bus) return { label: m.group_type_bus(), display: bus.name, ref: bus };
		const man = localized?.manufacturer;
		if (man?.length === 1)
			return {
				label: m.property_name_manufacturer({ count: 1 }),
				display: man[0].name,
				ref: man[0]
			};
		return null;
	});

	let launchVehicleRef = $derived.by<CrossRef | null>(() => {
		const lv = localized?.launch_vehicle;
		return lv ? { label: m.launch_vehicle(), display: lv.name, ref: lv } : null;
	});

	let launchSiteRef = $derived.by<CrossRef | null>(() => {
		const site = localized?.launch_site;
		if (!site?.length) return null;
		return { label: m.launch_site(), display: site[0].name, ref: site[0] };
	});

	let operatorRef = $derived.by<CrossRef | null>(() => {
		const ops = localized?.operators;
		if (ops?.length !== 1) return null;
		return { label: m.property_name_operators({ count: 1 }), display: ops[0].name, ref: ops[0] };
	});

	/** Matching on destination catches an operator that also built the craft;
	 *  matching on text catches Spire Global the constellation next to Spire
	 *  Global the operator, which reads as a duplicate whatever it links to. */
	function refKeys(c: CrossRef): string[] {
		return c.ref.primary_id ? [c.ref.primary_id, c.ref.name] : [c.ref.name];
	}

	function tileKey(c: CrossRef): string {
		return c.ref.primary_id ?? c.ref.name;
	}

	// The grid is 2 wide, so a third tile would leave a hole: fill both rows or
	// only the first. Order is priority order — the dropped tiles are the last.
	let cards = $derived.by(() => {
		const seen = new Set<string>();
		const available: CrossRef[] = [];
		for (const c of [
			orbitClassRef ?? lagrangeRef,
			carriedByRef,
			affiliationRef,
			platformRef,
			launchVehicleRef,
			launchSiteRef,
			operatorRef
		]) {
			if (c == null || refKeys(c).some((k) => seen.has(k))) continue;
			for (const k of refKeys(c)) seen.add(k);
			available.push(c);
		}
		return available.slice(0, available.length >= 4 ? 4 : available.length >= 2 ? 2 : 1);
	});

	// Each linked group's lead image, fetched lazily (bundles are cached, so this
	// also prefetches the tile's destination page).
	async function fetchHero(slug?: string): Promise<string | undefined> {
		if (!slug) return undefined;
		const detail = await fetchGroupDetail(slug);
		const img = detail.global?.images?.[0];
		return img ? pickImageUrl(img, 300) : undefined;
	}
	let tiles = $derived(
		cards.map((c) => ({
			card: c,
			// Only groups have a page with a lead image; an object ref would 404.
			hero: c.ref.primary_type === 'group' ? fetchHero(c.ref.primary_id) : undefined
		}))
	);

	function href(ref: EntityRef): string | undefined {
		if (!appState || !ref.primary_id) return undefined;
		// Every tile but `carried_by` points at a group; that one names a craft.
		return ref.primary_type === 'object'
			? focusHref(appState, ref.primary_id, ref.name)
			: serializeUrl(applyGroup(appState.view, ref.primary_id, ref.name));
	}

	function open(e: MouseEvent, ref: EntityRef) {
		if (!appState || !ref.primary_id) return;
		if (ref.primary_type === 'object') {
			focusClick(focusObject, ref.primary_id, ref.name)(e);
			return;
		}
		if (isModifiedClick(e)) return;
		e.preventDefault();
		appState.setGroup(ref.primary_id, ref.name);
	}
</script>

{#if tiles.length > 0}
	<div class="grid grid-cols-2 gap-2">
		{#each tiles as t (tileKey(t.card))}
			<CrossRefCard
				href={href(t.card.ref)}
				onclick={(e) => open(e, t.card.ref)}
				title={t.card.ref.name}
				hero={t.hero}
				display={t.card.display}
				label={t.card.label}
				class={tiles.length === 1 ? 'col-span-2' : ''}
			/>
		{/each}
	</div>
{/if}
