<!--
  What is being flown, read beside the trajectory it flies on. The craft
  picker is out of sight by now — Δv, Isp, and heat-shield figures here feed
  the ladder and arrival checks below.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { CraftSpec } from './craft-specs';
	import { vehicleName } from './vehicle-labels';
	import type { Vehicle } from '$lib/math/travel';

	interface Props {
		vehicle: Vehicle;
		specs: readonly CraftSpec[];
	}
	let { vehicle, specs }: Props = $props();
</script>

<section class="flex flex-col gap-2">
	<h4 class="truncate text-sm font-medium" title={vehicleName(vehicle)}>{vehicleName(vehicle)}</h4>
	<div class="border-border/60 border-t"></div>
	{#if specs.length > 0}
		<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
			{#each specs as spec (spec.label)}
				<dt class="text-muted-foreground">{spec.label}</dt>
				<dd class="text-end tabular-nums">
					{spec.value}{#if spec.note}<span class="text-muted-foreground ms-1 text-xs"
							>({spec.note})</span
						>{/if}
				</dd>
			{/each}
		</dl>
	{:else}
		<!-- Fiction and archetype drives have nothing published to state. -->
		<p class="text-muted-foreground text-xs">{m.travel_spec_unpublished()}</p>
	{/if}
</section>
