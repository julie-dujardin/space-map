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
	import { featureTypeDescription } from '$lib/format/feature-type';
	import { SAT_ORBIT_ZONES, CLASS_SLUG_PREFIX, orbitClassLabel } from '$lib/charts/orbit-zones';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import EntityLinks from './kit/EntityLinks.svelte';
	import YearHistogramChart from '../charts/YearHistogramChart.svelte';
	import GroupOrbitMap from '../charts/GroupOrbitMap.svelte';
	import ChildGroups from './ChildGroups.svelte';
	import CountPerBodyChart from '../charts/CountPerBodyChart.svelte';
	import PagedBarList from '../charts/PagedBarList.svelte';

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
	// GCAT variant name → Wikipedia ref, for variants matched to a Wikidata entity.
	let variantRefs = $derived(localized?.variant_refs ?? {});
	// Top individual reusable vehicles (Shuttle orbiters / Falcon cores) by flights.
	let reusableVehicles = $derived(global?.reusable_vehicles ?? []);
	let reusableRefs = $derived(localized?.reusable_vehicle_refs ?? {});
	let discoveryHistogram = $derived(global?.discovery_histogram);
	// IAU name approvals per year — a ft- page's own, or every type on the
	// Surface Features meta page.
	let approvalHistogram = $derived(global?.approval_histogram);
	// Meta page: which cultures the IAU drew names from (its `ethnicity` field).
	let namingOrigins = $derived(global?.naming_origins ?? []);
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

	// The IAU descriptor definition, suppressed when Wikidata's description says
	// the same thing — both come from the type's Wikidata entity for most codes.
	let featureTypeDefinition = $derived(
		global?.type === 'feature_type' ? featureTypeDescription(global.slug) : undefined
	);
	let showDefinition = $derived(
		!!featureTypeDefinition &&
			normalize(featureTypeDefinition) !== normalize(localized?.description)
	);

	function normalize(s: string | undefined): string {
		return (s ?? '').trim().toLowerCase().replace(/\.$/, '');
	}

	let featureBodies = $derived(global?.feature_bodies ?? []);

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

{#if showDefinition}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.group_iau_definition()}</h3>
		<div class="border-border/60 border-t"></div>
		<p class="text-muted-foreground pt-1 text-sm">{featureTypeDefinition}</p>
	</div>
{/if}

{#if featureBodies.length > 0}
	<CountPerBodyChart
		entries={featureBodies}
		title={m.group_features_per_body()}
		names={localized?.body_names}
		tab="features"
	/>
{/if}

{#if launchHistogram}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.group_launch_activity()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="pt-1">
			<YearHistogramChart histogram={launchHistogram} kind="launch" />
		</div>
	</div>
{/if}

{#snippet wikipediaLabel(name: string, ref: EntityRef | undefined)}
	{#if ref?.wikipedia}
		<a
			href={ref.wikipedia}
			target="_blank"
			rel="noopener"
			class="hover:text-foreground inline-flex items-center gap-1 align-bottom underline"
			>{name}<ExternalLinkIcon class="size-3 shrink-0" /></a
		>
	{:else}
		{name}
	{/if}
{/snippet}

<PagedBarList entries={variants} title={m.group_variants()} unit={m.group_variants_launches()}>
	{#snippet label(v)}
		<span class="min-w-0 truncate">
			{@render wikipediaLabel(v.name, variantRefs[v.name])}
			{#if v.leo_capacity_kg}
				<span class="text-muted-foreground text-xs"
					>· {m.group_variant_payload_leo({ kg: formatNumber(v.leo_capacity_kg) })}</span
				>
			{/if}
		</span>
	{/snippet}
</PagedBarList>

<PagedBarList
	entries={reusableVehicles}
	title={m.group_reusable_vehicles()}
	unit={m.group_reusable_flights()}
>
	{#snippet label(v)}
		<span class="min-w-0 truncate">
			{@render wikipediaLabel(v.name, reusableRefs[v.name])}
		</span>
	{/snippet}
</PagedBarList>

{#if namingOrigins.length > 0}
	<CountPerBodyChart entries={namingOrigins} title={m.group_naming_origins()} />
{/if}

{#if approvalHistogram}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.group_naming_activity()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="pt-1">
			<YearHistogramChart histogram={approvalHistogram} kind="naming" />
		</div>
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

<!-- Launch sites and constellations link the same way: to the group page when
     the row is one of ours, else out to Wikipedia. -->
{#snippet groupOrWikipediaLabel(e: {
	name: string;
	primary_type?: string;
	primary_id?: string;
	wikipedia?: string;
})}
	{#if appState && e.primary_type === 'group' && e.primary_id}
		{@const slug = e.primary_id}
		{@const name = e.name}
		<a
			href={groupHref(slug, name)}
			onclick={(ev) => handleGroupClick(ev, slug, name)}
			class="pointer-events-auto hover:text-foreground inline-flex min-w-0 items-center gap-1 truncate underline"
			><span class="truncate">{e.name}</span></a
		>
	{:else if e.wikipedia}
		<a
			href={e.wikipedia}
			target="_blank"
			rel="noopener"
			class="pointer-events-auto hover:text-foreground truncate underline">{e.name}</a
		>
	{:else}
		<span class="truncate">{e.name}</span>
	{/if}
{/snippet}

{#if showLaunchSites}
	<PagedBarList
		entries={launchSites}
		title={m.group_top_launch_sites()}
		unit={m.satellites_label()}
	>
		{#snippet label(site)}
			{@render groupOrWikipediaLabel(site)}
		{/snippet}
	</PagedBarList>
{/if}

<PagedBarList
	entries={constellations}
	title={m.group_top_constellations()}
	unit={m.satellites_label()}
>
	{#snippet label(c)}
		{@render groupOrWikipediaLabel(c)}
	{/snippet}
</PagedBarList>
