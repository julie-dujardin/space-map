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
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import { EARTH_ID, SUN_ID } from '$lib/constants';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import {
		CLASS_SLUG_PREFIX,
		classifyEarthOrbit,
		orbitClassLabel,
		orbitClassShortLabel
	} from '$lib/charts/orbit-zones';
	import { classifyLagrange } from '$lib/math/orbit/lagrange';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import { pickImageUrl } from '$lib/fetch/objects/images';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		/** TLE-derived elements (for the orbit inclination band). */
		orbitElements?: OrbitalElements;
		/** Focused body — used to detect a probe's Sun–Earth L-point at sim time. */
		body?: PositionedBody;
		jd: number;
	}
	let { global, localized, orbitElements, body, jd }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const ctx = getContext<ContextManager | undefined>('ctx');

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

	// Probe orbit class: Sun–Earth L1/L2 from live scene geometry. Mutually
	// exclusive with the earth-sat orbit-class slot above.
	let lagrangeRef = $derived.by<CrossRef | null>(() => {
		if (!ctx || !body || body.data.orbitalSource !== OrbitalSource.SPICE_PROBE) return null;
		void jd; // re-run as sim time advances; positions below are read live
		const earth = ctx.getBody(EARTH_ID)?.position;
		const sun = ctx.getBody(SUN_ID)?.position;
		const p = ctx.getBody(body.data.id)?.position ?? body.position;
		if (!earth || !sun) return null;
		const geocentric = [p[0] - earth[0], p[1] - earth[1], p[2] - earth[2]] as const;
		const earthToSun = [sun[0] - earth[0], sun[1] - earth[1], sun[2] - earth[2]] as const;
		const point = classifyLagrange(geocentric, earthToSun);
		if (!point) return null;
		return {
			label: m.orbit(),
			display: orbitClassShortLabel(point),
			ref: groupRef(orbitClassLabel(point), `${CLASS_SLUG_PREFIX}${point}`)
		};
	});

	// Mission first, then the first single-valued constellation / operator /
	// manufacturer (arrays count only when there's exactly one clear primary).
	let affiliationRef = $derived.by<CrossRef | null>(() => {
		const mission = global?.mission ?? global?.part_of_mission;
		if (mission) return { label: m.mission(), display: mission.name, ref: fragmentRef(mission) };
		const con = localized?.constellation;
		if (con) return { label: m.group_type_constellation(), display: con.name, ref: con };
		const ops = localized?.operators;
		if (ops?.length === 1)
			return { label: m.property_name_operators({ count: 1 }), display: ops[0].name, ref: ops[0] };
		const man = localized?.manufacturer;
		if (man?.length === 1)
			return {
				label: m.property_name_manufacturer({ count: 1 }),
				display: man[0].name,
				ref: man[0]
			};
		return null;
	});

	// Launch: launch vehicle when present, otherwise the launch site.
	let launchRef = $derived.by<CrossRef | null>(() => {
		const lv = localized?.launch_vehicle;
		if (lv) return { label: m.launch_vehicle(), display: lv.name, ref: lv };
		const site = localized?.launch_site;
		if (site && site.length > 0)
			return { label: m.launch_site(), display: site[0].name, ref: site[0] };
		return null;
	});

	// Cap at two image tiles; take the first available in priority order.
	let cards = $derived(
		[orbitClassRef ?? lagrangeRef, affiliationRef, launchRef]
			.filter((c): c is CrossRef => c != null)
			.slice(0, 2)
	);

	// Each linked group's lead image, fetched lazily (bundles are cached, so this
	// also prefetches the tile's destination page).
	async function fetchHero(slug?: string): Promise<string | undefined> {
		if (!slug) return undefined;
		const detail = await fetchGroupDetail(slug);
		const img = detail.global?.images?.[0];
		return img ? pickImageUrl(img, 300) : undefined;
	}
	let tiles = $derived(cards.map((c) => ({ card: c, hero: fetchHero(c.ref.primary_id) })));

	function href(ref: EntityRef): string | undefined {
		if (!appState || !ref.primary_id) return undefined;
		return serializeUrl(applyGroup(appState.view, ref.primary_id, ref.name));
	}

	function open(e: MouseEvent, ref: EntityRef) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState || !ref.primary_id) return;
		e.preventDefault();
		appState.setGroup(ref.primary_id, ref.name);
	}
</script>

{#if tiles.length > 0}
	<div class="grid grid-cols-2 gap-2">
		{#each tiles as t (t.card.label)}
			<a
				href={href(t.card.ref)}
				onclick={(e) => open(e, t.card.ref)}
				title={t.card.ref.name}
				class="border-border/60 bg-muted pointer-events-auto relative block h-20 overflow-hidden rounded-md border"
				class:col-span-2={tiles.length === 1}
			>
				{#await t.hero then src}
					{#if src}
						<img
							{src}
							alt=""
							loading="lazy"
							decoding="async"
							class="absolute inset-0 size-full object-cover"
						/>
					{/if}
				{/await}
				<div
					class="absolute inset-0 bg-gradient-to-t from-black/85 via-black/30 to-transparent"
				></div>
				<div class="absolute inset-x-0 bottom-0 flex flex-col gap-0.5 p-2.5">
					<span class="truncate text-sm font-semibold text-white">{t.card.display}</span>
					<span class="truncate text-[10px] uppercase text-white/70">{t.card.label}</span>
				</div>
			</a>
		{/each}
	</div>
{/if}
