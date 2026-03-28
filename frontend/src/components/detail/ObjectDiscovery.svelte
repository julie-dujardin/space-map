<script lang="ts">
	import { Separator } from '$lib/components/ui/separator/index.js';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData, EntityRef } from '$lib/object-data';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
	}

	let { global, localized }: Props = $props();

	// Discovery date: wikipedia records the discovery date, sbdb the first observation
	// different for ceres: 1801 (discovery) vs 1995 (first observation by hubble telescope)
	// Wikipedia seems to have the more relevant data here
	let discoveryDate = $derived(global?.wikidata?.discovery_date ?? global?.sbdb?.first_obs);
	let launchDate = $derived(global?.wikidata?.launch_date);
	let discoverers = $derived(localized?.discoverers);
	let discoverySite = $derived(localized?.discovery_site);
	let namedAfter = $derived(localized?.named_after);
	let minorPlanetGroup = $derived(localized?.minor_planet_group);
	let asteroidFamily = $derived(localized?.asteroid_family);
	let isNeo = $derived(global?.sbdb?.neo);
	let isPha = $derived(global?.sbdb?.pha);
	let orbitClass = $derived(global?.sbdb?.class);
	let sats = $derived(global?.sbdb?.sats);

	// Spacecraft fields
	let operator = $derived(localized?.operator);
	let manufacturer = $derived(localized?.manufacturer);
	let launchVehicle = $derived(localized?.launch_vehicle);
	let launchSite = $derived(localized?.launch_site);

	let hasContent = $derived(
		discoveryDate ||
			launchDate ||
			discoverers ||
			discoverySite ||
			namedAfter ||
			minorPlanetGroup ||
			asteroidFamily ||
			isNeo ||
			isPha ||
			orbitClass ||
			operator ||
			manufacturer ||
			launchVehicle ||
			launchSite
	);
</script>

{#snippet entityLink(entity: EntityRef)}
	{#if entity.wikipedia}
		<a
			href={entity.wikipedia}
			target="_blank"
			rel="noopener noreferrer"
			class="underline hover:text-foreground">{entity.name}</a
		>
	{:else}
		{entity.name}
	{/if}
{/snippet}

{#if hasContent}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">
			{global?.type === 'spacecraft' ? m.mission() : m.discovery()}
		</h3>
		<Separator />

		{#if isNeo || isPha}
			<div class="flex gap-1.5 mb-1">
				{#if isNeo}<Badge variant="outline">{m.neo()}</Badge>{/if}
				{#if isPha}<Badge variant="destructive">{m.pha()}</Badge>{/if}
			</div>
		{/if}

		<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
			{#if discoveryDate}
				<dt class="text-muted-foreground">{m.first_observed()}</dt>
				<dd class="text-right">{discoveryDate}</dd>
			{/if}
			{#if launchDate}
				<dt class="text-muted-foreground">{m.launch_date()}</dt>
				<dd class="text-right">{launchDate}</dd>
			{/if}
			{#if discoverers && discoverers.length > 0}
				<dt class="text-muted-foreground">
					{discoverers.length > 1 ? m.discoverers() : m.discoverer()}
				</dt>
				<dd class="text-right text-muted-foreground">
					{#each discoverers as d, i (d.name)}
						{#if i > 0},
						{/if}{@render entityLink(d)}
					{/each}
				</dd>
			{/if}
			{#if discoverySite}
				<dt class="text-muted-foreground">{m.discovery_site()}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLink(discoverySite)}</dd>
			{/if}
			{#if namedAfter}
				<dt class="text-muted-foreground">{m.named_after()}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLink(namedAfter)}</dd>
			{/if}
			{#if orbitClass}
				<dt class="text-muted-foreground">{m.orbit_class()}</dt>
				<dd class="text-right">{orbitClass}</dd>
			{/if}
			{#if minorPlanetGroup}
				<dt class="text-muted-foreground">{m.group()}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLink(minorPlanetGroup)}</dd>
			{/if}
			{#if asteroidFamily}
				<dt class="text-muted-foreground">{m.family()}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLink(asteroidFamily)}</dd>
			{/if}
			{#if sats != null && sats > 0}
				<dt class="text-muted-foreground">{m.known_satellites()}</dt>
				<dd class="text-right">{sats}</dd>
			{/if}
			{#if operator}
				<dt class="text-muted-foreground">{m.operator()}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLink(operator)}</dd>
			{/if}
			{#if manufacturer}
				<dt class="text-muted-foreground">{m.manufacturer()}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLink(manufacturer)}</dd>
			{/if}
			{#if launchVehicle}
				<dt class="text-muted-foreground">{m.launch_vehicle()}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLink(launchVehicle)}</dd>
			{/if}
			{#if launchSite}
				<dt class="text-muted-foreground">{m.launch_site()}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLink(launchSite)}</dd>
			{/if}
		</dl>
	</div>
{/if}
