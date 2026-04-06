<script lang="ts">
	import { Separator } from '$lib/components/ui/separator/index.js';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type {
		GlobalObjectData,
		LocalizedObjectData,
		EntityRef
	} from '$lib/fetch/objects/object-data';
	import { formatWikidataDate } from '$lib/format/date';
	import { ucfirst } from '$lib/format/quantities';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
	}

	let { global, localized }: Props = $props();

	// Discovery date: wikipedia records the discovery date, sbdb the first observation
	// different for ceres: 1801 (discovery) vs 1995 (first observation by hubble telescope)
	// Wikipedia seems to have the more relevant data here
	let discoveryDate = $derived(global?.wikidata?.discovery_date?.[0] ?? global?.sbdb?.first_obs);
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

{#snippet entityLinks(entities: EntityRef[])}
	<span class="flex flex-wrap justify-end gap-x-1">
		{#each entities as e (e.name)}
			<span class="whitespace-nowrap">{@render entityLink(e)}</span>
		{/each}
	</span>
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
				<dt class="text-muted-foreground">{ucfirst(m.first_observed())}</dt>
				<dd class="text-right">{formatWikidataDate(discoveryDate)}</dd>
			{/if}
			{#if launchDate}
				<dt class="text-muted-foreground">{ucfirst(m.launch_date())}</dt>
				<dd class="text-right">{formatWikidataDate(launchDate)}</dd>
			{/if}
			{#if discoverers && discoverers.length > 0}
				<dt class="text-muted-foreground">
					{ucfirst(discoverers.length > 1 ? m.discoverers() : m.discoverer())}
				</dt>
				<dd class="text-right text-muted-foreground flex flex-wrap justify-end gap-x-1">
					{#each discoverers as d (d.name)}
						<span class="whitespace-nowrap">{@render entityLink(d)}</span>
					{/each}
				</dd>
			{/if}
			{#if discoverySite && discoverySite.length > 0}
				<dt class="text-muted-foreground">{ucfirst(m.discovery_site())}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLinks(discoverySite)}</dd>
			{/if}
			{#if namedAfter && namedAfter.length > 0}
				<dt class="text-muted-foreground">{ucfirst(m.property_name_named_after())}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLinks(namedAfter)}</dd>
			{/if}
			{#if orbitClass}
				<dt class="text-muted-foreground">{ucfirst(m.orbit_class())}</dt>
				<dd class="text-right">{orbitClass}</dd>
			{/if}
			{#if minorPlanetGroup && minorPlanetGroup.length > 0}
				<dt class="text-muted-foreground">{ucfirst(m.property_name_minor_planet_group())}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLinks(minorPlanetGroup)}</dd>
			{/if}
			{#if asteroidFamily}
				<dt class="text-muted-foreground">{ucfirst(m.property_name_asteroid_family())}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLink(asteroidFamily)}</dd>
			{/if}
			{#if sats != null && sats > 0}
				<dt class="text-muted-foreground">{ucfirst(m.known_satellites())}</dt>
				<dd class="text-right">{sats}</dd>
			{/if}
			{#if operator && operator.length > 0}
				<dt class="text-muted-foreground">{ucfirst(m.property_name_operator())}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLinks(operator)}</dd>
			{/if}
			{#if manufacturer && manufacturer.length > 0}
				<dt class="text-muted-foreground">{ucfirst(m.property_name_manufacturer())}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLinks(manufacturer)}</dd>
			{/if}
			{#if launchVehicle}
				<dt class="text-muted-foreground">{ucfirst(m.launch_vehicle())}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLink(launchVehicle)}</dd>
			{/if}
			{#if launchSite && launchSite.length > 0}
				<dt class="text-muted-foreground">{ucfirst(m.launch_site())}</dt>
				<dd class="text-right text-muted-foreground">{@render entityLinks(launchSite)}</dd>
			{/if}
		</dl>
	</div>
{/if}
