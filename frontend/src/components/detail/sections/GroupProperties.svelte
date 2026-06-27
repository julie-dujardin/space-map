<script lang="ts">
	import { getContext } from 'svelte';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalGroupData, LocalizedGroupData } from '$lib/fetch/groups/details';
	import type { EntityRef } from '$lib/fetch/objects/object-data';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { formatIsoDate } from '$lib/format/date';
	import { formatNumber } from '$lib/format/quantities';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import { fetchEarthMembership } from '$lib/fetch/groups/membership';
	import { SAT_ORBIT_ZONES, CLASS_SLUG_PREFIX, orbitClassLabel } from '$lib/charts/orbit-zones';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import EntityLinks from './kit/EntityLinks.svelte';
	import YearHistogramChart from '../charts/YearHistogramChart.svelte';
	import GroupOrbitMap from '../charts/GroupOrbitMap.svelte';
	import ChildGroups from './ChildGroups.svelte';

	const appState = getContext<AppState | undefined>('appState');

	interface Props {
		global: GlobalGroupData | null;
		localized: LocalizedGroupData | null;
	}

	let { global, localized }: Props = $props();

	let inception = $derived(global?.inception);
	let dissolved = $derived(global?.dissolved);
	let launchHistogram = $derived(global?.launch_histogram);
	// Launch-vehicle variant breakdown (most-launched first), with GCAT specs.
	let variants = $derived(global?.variants ?? []);
	let maxVariantCount = $derived(variants.length > 0 ? Math.max(...variants.map((v) => v.n)) : 0);
	// GCAT variant name → Wikipedia ref, for variants matched to a Wikidata entity.
	let variantRefs = $derived(localized?.variant_refs ?? {});
	// Top individual reusable vehicles (Shuttle orbiters / Falcon cores) by flights.
	let reusableVehicles = $derived(global?.reusable_vehicles ?? []);
	let maxReusableCount = $derived(
		reusableVehicles.length > 0 ? Math.max(...reusableVehicles.map((v) => v.n)) : 0
	);
	let reusableRefs = $derived(localized?.reusable_vehicle_refs ?? {});
	let discoveryHistogram = $derived(global?.discovery_histogram);
	let operators = $derived(localized?.operators ?? []);
	let manufacturers = $derived(localized?.manufacturers ?? []);
	let countries = $derived(localized?.country_of_origin ?? []);
	let launchSites = $derived(localized?.launch_sites ?? []);
	let constellations = $derived(localized?.constellations ?? []);
	// Satellite buses flown by this group's members (constellations + manufacturers).
	let busChildGroups = $derived((localized?.child_groups ?? []).filter((c) => c.role === 'bus'));

	// Hide the top-launch-sites and orbit-class breakdowns when constellations
	// are shown — each constellation already surfaces its own, so they're redundant.
	let showLaunchSites = $derived(launchSites.length > 0 && constellations.length === 0);

	let maxSiteCount = $derived(
		launchSites.length > 0 ? Math.max(...launchSites.map((s) => s.n)) : 0
	);
	let maxConstellationCount = $derived(
		constellations.length > 0 ? Math.max(...constellations.map((c) => c.n)) : 0
	);

	// Orbit-class breakdown for the focused group: intersect the cached
	// membership map against each class-* slug, drop zones with ≤10 % share.
	let isEarthSatGroup = $derived(global?.applies_to === 'earth_sat');
	let isOrbitClassGroup = $derived(global?.type === 'earth_orbit_class');
	const ORBIT_CLASS_MIN_SHARE = 0.1;
	let orbitClassRefs = $state<EntityRef[]>([]);
	$effect(() => {
		if (!global || !isEarthSatGroup || isOrbitClassGroup) {
			orbitClassRefs = [];
			return;
		}
		const slug = global.slug;
		fetchEarthMembership().then((mem) => {
			const focused = new Set(mem[slug] ?? []);
			if (focused.size === 0) {
				orbitClassRefs = [];
				return;
			}
			const minCount = focused.size * ORBIT_CLASS_MIN_SHARE;
			const hits: { name: string; n: number; slug: string }[] = [];
			for (const className of Object.keys(SAT_ORBIT_ZONES)) {
				const members = mem[`${CLASS_SLUG_PREFIX}${className}`];
				if (!members) continue;
				let n = 0;
				for (const id of members) if (focused.has(id)) n++;
				if (n > minCount) {
					hits.push({
						name: orbitClassLabel(className),
						n,
						slug: `${CLASS_SLUG_PREFIX}${className}`
					});
				}
			}
			hits.sort((a, b) => b.n - a.n);
			orbitClassRefs = hits.map((h) => ({
				name: h.name,
				primary_type: 'group',
				primary_id: h.slug
			}));
		});
	});

	let hasMission = $derived(
		!!inception ||
			!!dissolved ||
			operators.length > 0 ||
			manufacturers.length > 0 ||
			countries.length > 0
	);

	let groupType = $derived(global?.type);
	let sectionTitle = $derived(
		groupType === 'constellation' ? m.group_section_programme() : m.group_section_about()
	);
	let inceptionLabel = $derived(
		groupType === 'launch_site'
			? m.group_label_opened()
			: groupType === 'constellation'
				? m.group_label_started()
				: m.group_label_founded()
	);
	let dissolvedLabel = $derived(
		groupType === 'launch_site'
			? m.group_label_closed()
			: groupType === 'constellation'
				? m.group_label_retired()
				: m.group_label_dissolved()
	);
	let countryLabel = $derived(
		groupType === 'launch_site' ? m.group_label_country() : m.group_label_country_of_origin()
	);

	function groupHref(slug: string, name: string): string | undefined {
		if (!appState) return undefined;
		return serializeUrl(applyGroup(appState.view, slug, name));
	}

	function handleGroupClick(e: MouseEvent, slug: string, name: string) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		e.preventDefault();
		appState.setGroup(slug, name);
	}
</script>

<GroupOrbitMap {global} />

{#if launchHistogram}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.group_launch_activity()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="pt-1">
			<YearHistogramChart histogram={launchHistogram} kind="launch" />
		</div>
	</div>
{/if}

{#if variants.length > 0}
	<div class="flex flex-col gap-1">
		<div class="flex items-baseline justify-between">
			<h3 class="text-sm font-medium">{m.group_variants()}</h3>
			<span class="text-muted-foreground text-[10px] uppercase">{m.group_variants_launches()}</span>
		</div>
		<div class="border-border/60 border-t"></div>
		<ul class="flex flex-col gap-2 pt-1 text-sm">
			{#each variants as v (v.name)}
				<li class="flex flex-col gap-1">
					<div class="flex items-baseline justify-between gap-2">
						<span class="min-w-0 truncate">
							{#if variantRefs[v.name]?.wikipedia}
								<a
									href={variantRefs[v.name].wikipedia}
									target="_blank"
									rel="noopener"
									class="hover:text-foreground inline-flex items-center gap-1 align-bottom underline"
									>{v.name}<ExternalLinkIcon class="size-3 shrink-0" /></a
								>
							{:else}
								{v.name}
							{/if}
							{#if v.leo_capacity_kg}
								<span class="text-muted-foreground text-xs"
									>· {m.group_variant_payload_leo({ kg: formatNumber(v.leo_capacity_kg) })}</span
								>
							{/if}
						</span>
						<span class="text-muted-foreground tabular-nums">{formatNumber(v.n)}</span>
					</div>
					<div class="bg-muted h-1 overflow-hidden rounded-full">
						<div
							class="bg-primary h-full rounded-full"
							style:width="{maxVariantCount > 0 ? (v.n / maxVariantCount) * 100 : 0}%"
						></div>
					</div>
				</li>
			{/each}
		</ul>
	</div>
{/if}

{#if reusableVehicles.length > 0}
	<div class="flex flex-col gap-1">
		<div class="flex items-baseline justify-between">
			<h3 class="text-sm font-medium">{m.group_reusable_vehicles()}</h3>
			<span class="text-muted-foreground text-[10px] uppercase">{m.group_reusable_flights()}</span>
		</div>
		<div class="border-border/60 border-t"></div>
		<ul class="flex flex-col gap-2 pt-1 text-sm">
			{#each reusableVehicles as v (v.name)}
				<li class="flex flex-col gap-1">
					<div class="flex items-baseline justify-between gap-2">
						<span class="min-w-0 truncate">
							{#if reusableRefs[v.name]?.wikipedia}
								<a
									href={reusableRefs[v.name].wikipedia}
									target="_blank"
									rel="noopener"
									class="hover:text-foreground inline-flex items-center gap-1 align-bottom underline"
									>{v.name}<ExternalLinkIcon class="size-3 shrink-0" /></a
								>
							{:else}
								{v.name}
							{/if}
						</span>
						<span class="text-muted-foreground tabular-nums">{formatNumber(v.n)}</span>
					</div>
					<div class="bg-muted h-1 overflow-hidden rounded-full">
						<div
							class="bg-primary h-full rounded-full"
							style:width="{maxReusableCount > 0 ? (v.n / maxReusableCount) * 100 : 0}%"
						></div>
					</div>
				</li>
			{/each}
		</ul>
	</div>
{/if}

{#if discoveryHistogram}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.group_discovery_activity()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="pt-1">
			<YearHistogramChart histogram={discoveryHistogram} kind="discovery" />
		</div>
	</div>
{/if}

{#if hasMission}
	<Section title={sectionTitle}>
		{#if inception}
			<Row label={inceptionLabel} value={formatIsoDate(inception)} />
		{/if}
		{#if dissolved}
			<Row label={dissolvedLabel} value={formatIsoDate(dissolved)} />
		{/if}
		{#if operators.length > 0}
			<Row label={m.group_label_operators({ count: operators.length })}>
				<EntityLinks entities={operators} />
			</Row>
		{/if}
		{#if manufacturers.length > 0}
			<Row label={m.group_label_manufacturers({ count: manufacturers.length })}>
				<EntityLinks entities={manufacturers} />
			</Row>
		{/if}
		{#if countries.length > 0}
			<Row label={countryLabel}>
				<EntityLinks entities={countries} />
			</Row>
		{/if}
	</Section>
{/if}

{#if busChildGroups.length}
	<ChildGroups childGroups={busChildGroups} />
{/if}

{#if orbitClassRefs.length > 0 && constellations.length === 0}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.group_orbit_classes()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="pt-1">
			<EntityLinks entities={orbitClassRefs} />
		</div>
	</div>
{/if}

{#if showLaunchSites}
	<div class="flex flex-col gap-1">
		<div class="flex items-baseline justify-between">
			<h3 class="text-sm font-medium">{m.group_top_launch_sites()}</h3>
			<span class="text-muted-foreground text-[10px] uppercase">{m.satellites_label()}</span>
		</div>
		<div class="border-border/60 border-t"></div>
		<ul class="flex flex-col gap-2 pt-1 text-sm">
			{#each launchSites as site (site.name)}
				<li class="flex flex-col gap-1">
					<div class="flex items-baseline justify-between gap-2">
						{#if appState && site.primary_type === 'group' && site.primary_id}
							{@const slug = site.primary_id}
							{@const name = site.name}
							<a
								href={groupHref(slug, name)}
								onclick={(e) => handleGroupClick(e, slug, name)}
								class="pointer-events-auto hover:text-foreground inline-flex min-w-0 items-center gap-1 truncate underline"
								><span class="truncate">{site.name}</span></a
							>
						{:else if site.wikipedia}
							<a
								href={site.wikipedia}
								target="_blank"
								rel="noopener"
								class="pointer-events-auto hover:text-foreground truncate underline">{site.name}</a
							>
						{:else}
							<span class="truncate">{site.name}</span>
						{/if}
						<span class="text-muted-foreground tabular-nums">{formatNumber(site.n)}</span>
					</div>
					<div class="bg-muted h-1 overflow-hidden rounded-full">
						<div
							class="bg-primary h-full rounded-full"
							style:width="{maxSiteCount > 0 ? (site.n / maxSiteCount) * 100 : 0}%"
						></div>
					</div>
				</li>
			{/each}
		</ul>
	</div>
{/if}

{#if constellations.length > 0}
	<div class="flex flex-col gap-1">
		<div class="flex items-baseline justify-between">
			<h3 class="text-sm font-medium">{m.group_top_constellations()}</h3>
			<span class="text-muted-foreground text-[10px] uppercase">{m.satellites_label()}</span>
		</div>
		<div class="border-border/60 border-t"></div>
		<ul class="flex flex-col gap-2 pt-1 text-sm">
			{#each constellations as c (c.name)}
				<li class="flex flex-col gap-1">
					<div class="flex items-baseline justify-between gap-2">
						{#if appState && c.primary_type === 'group' && c.primary_id}
							{@const slug = c.primary_id}
							{@const name = c.name}
							<a
								href={groupHref(slug, name)}
								onclick={(e) => handleGroupClick(e, slug, name)}
								class="pointer-events-auto hover:text-foreground inline-flex min-w-0 items-center gap-1 truncate underline"
								><span class="truncate">{c.name}</span></a
							>
						{:else if c.wikipedia}
							<a
								href={c.wikipedia}
								target="_blank"
								rel="noopener"
								class="pointer-events-auto hover:text-foreground truncate underline">{c.name}</a
							>
						{:else}
							<span class="truncate">{c.name}</span>
						{/if}
						<span class="text-muted-foreground tabular-nums">{formatNumber(c.n)}</span>
					</div>
					<div class="bg-muted h-1 overflow-hidden rounded-full">
						<div
							class="bg-primary h-full rounded-full"
							style:width="{maxConstellationCount > 0 ? (c.n / maxConstellationCount) * 100 : 0}%"
						></div>
					</div>
				</li>
			{/each}
		</ul>
	</div>
{/if}
