<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalGroupData, LocalizedGroupData } from '$lib/fetch/groups/details';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { groupTypeLabel } from '$lib/format/group';
	import { formatIsoDate } from '$lib/format/date';
	import { formatNumber } from '$lib/format/quantities';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import Section from './Section.svelte';
	import Row from './Row.svelte';
	import EntityLinks from './EntityLinks.svelte';
	import YearHistogramChart from './YearHistogramChart.svelte';
	import GroupOrbitMap from './GroupOrbitMap.svelte';

	const appState = getContext<AppState | undefined>('appState');

	interface Props {
		global: GlobalGroupData | null;
		localized: LocalizedGroupData | null;
	}

	let { global, localized }: Props = $props();

	let inception = $derived(global?.inception);
	let dissolved = $derived(global?.dissolved);
	let launchHistogram = $derived(global?.launch_histogram);
	let discoveryHistogram = $derived(global?.discovery_histogram);
	let operators = $derived(localized?.operators ?? []);
	let manufacturers = $derived(localized?.manufacturers ?? []);
	let countries = $derived(localized?.country_of_origin ?? []);
	let launchSites = $derived(localized?.launch_sites ?? []);
	let constellations = $derived(localized?.constellations ?? []);
	let related = $derived(localized?.related_groups ?? []);

	let maxSiteCount = $derived(
		launchSites.length > 0 ? Math.max(...launchSites.map((s) => s.n)) : 0
	);
	let maxConstellationCount = $derived(
		constellations.length > 0 ? Math.max(...constellations.map((c) => c.n)) : 0
	);

	let hasMission = $derived(
		!!inception ||
			!!dissolved ||
			operators.length > 0 ||
			manufacturers.length > 0 ||
			countries.length > 0 ||
			related.length > 0
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

{#if launchHistogram}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.group_launch_activity()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="pt-1">
			<YearHistogramChart histogram={launchHistogram} kind="launch" />
		</div>
	</div>
{/if}

<GroupOrbitMap {global} />

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
			<Row label={m.group_label_operators()}>
				<EntityLinks entities={operators} />
			</Row>
		{/if}
		{#if manufacturers.length > 0}
			<Row label={m.group_label_manufacturers()}>
				<EntityLinks entities={manufacturers} />
			</Row>
		{/if}
		{#if countries.length > 0}
			<Row label={countryLabel}>
				<EntityLinks entities={countries} />
			</Row>
		{/if}
		{#each related as r (r.primary_id)}
			<Row label={groupTypeLabel(r.role)}>
				<EntityLinks entities={[r]} />
			</Row>
		{/each}
	</Section>
{/if}

{#if launchSites.length > 0}
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
