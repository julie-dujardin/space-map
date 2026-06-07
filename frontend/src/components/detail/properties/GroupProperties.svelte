<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalGroupData, LocalizedGroupData } from '$lib/fetch/groups/details';
	import { formatIsoDate } from '$lib/format/date';
	import { formatNumber } from '$lib/format/quantities';
	import Section from './Section.svelte';
	import Row from './Row.svelte';
	import EntityLinks from './EntityLinks.svelte';
	import LaunchActivityChart from './LaunchActivityChart.svelte';

	interface Props {
		global: GlobalGroupData | null;
		localized: LocalizedGroupData | null;
	}

	let { global, localized }: Props = $props();

	let inception = $derived(global?.inception);
	let dissolved = $derived(global?.dissolved);
	let histogram = $derived(global?.launch_histogram);
	let operators = $derived(localized?.operators ?? []);
	let countries = $derived(localized?.country_of_origin ?? []);
	let launchSites = $derived(localized?.launch_sites ?? []);

	let maxSiteCount = $derived(
		launchSites.length > 0 ? Math.max(...launchSites.map((s) => s.n)) : 0
	);

	let hasMission = $derived(
		!!inception || !!dissolved || operators.length > 0 || countries.length > 0
	);
</script>

{#if histogram}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.group_launch_activity()}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="pt-1">
			<LaunchActivityChart {histogram} />
		</div>
	</div>
{/if}

{#if hasMission}
	<Section title={m.mission()}>
		{#if inception}
			<Row label={m.property_name_inception()} value={formatIsoDate(inception)} />
		{/if}
		{#if dissolved}
			<Row label={m.property_name_dissolved()} value={formatIsoDate(dissolved)} />
		{/if}
		{#if operators.length > 0}
			<Row label={m.property_name_operators()}>
				<EntityLinks entities={operators} />
			</Row>
		{/if}
		{#if countries.length > 0}
			<Row label={m.property_name_country_of_origin()}>
				<EntityLinks entities={countries} />
			</Row>
		{/if}
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
						{#if site.wikipedia}
							<a
								href={site.wikipedia}
								target="_blank"
								rel="noopener"
								class="hover:text-foreground truncate underline">{site.name}</a
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
