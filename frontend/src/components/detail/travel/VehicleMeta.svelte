<!--
  The two lines under a craft's name: Wikidata's one-liner, then the stats —
  shared between the picker's rows and the closed field showing the choice.
-->
<script lang="ts">
	import type { Manifest, Route, Vehicle } from '$lib/math/travel';
	import { vehicleDescription, vehicleStatsParts } from './vehicle-labels';

	interface Props {
		vehicle: Vehicle;
		/** The trajectory being read, so the stats can answer against it. */
		route: Route | null;
		manifest: Manifest;
	}
	let { vehicle, route, manifest }: Props = $props();

	let description = $derived(vehicleDescription(vehicle));
	let stats = $derived(vehicleStatsParts(vehicle, route, manifest));
</script>

{#if description}
	<span class="text-muted-foreground block truncate text-[11px]">{description}</span>
{/if}
{#if stats.length > 0}
	<span class="text-muted-foreground block text-[11px] tabular-nums">
		{stats.join(' · ')}
	</span>
{/if}
