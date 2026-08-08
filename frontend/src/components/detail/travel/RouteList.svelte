<!--
  The trajectories as one line each: what it is and when it runs on the left,
  what it costs on the right.

  A route the chosen craft cannot fly stays visible and goes quiet, with the
  reason in place of its figures — hiding it would leave the panel silently
  short of options.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { RouteChoice, RouteProfile } from '$lib/math/travel';
	import { formatJulianDate } from '$lib/format/date';
	import { formatQuantity } from '$lib/format/quantities';
	import type { TravelPanelState } from '$lib/travel/panel.svelte';
	import { formatTripTime } from '$lib/travel/format';
	import { departureNote } from './vehicle-labels';

	interface Props {
		state: TravelPanelState;
	}
	let { state }: Props = $props();

	const PROFILE_LABEL: Record<RouteProfile, () => string> = {
		fast: m.travel_profile_fast,
		balanced: m.travel_profile_balanced,
		efficient: m.travel_profile_efficient
	};

	function blockedText(choice: RouteChoice): string | null {
		const result = state.feasibility(choice.route);
		if (!result || result.status === 'ok') return null;
		if (result.status === 'over-c3') {
			return m.travel_needs_c3({ value: choice.route.c3Km2S2.toFixed(0) });
		}
		if (result.status === 'insufficient-dv') {
			return m.travel_needs_dv({ value: choice.route.inSpaceDvKms.toFixed(1) });
		}
		// The craft and the trip disagree about where it starts, which is a
		// statement about the craft rather than about this particular route.
		if (result.status === 'wrong-departure' && state.vehicle) {
			return departureNote(state.vehicle);
		}
		// A launcher's payload is what it can send to *this* energy, so the same
		// cargo clears one trajectory and not the next.
		if (result.status === 'over-payload' && result.payloadKg !== undefined) {
			return m.travel_lifts({
				value: formatQuantity({ value: result.payloadKg, unit: 'kilogram' }, true)
			});
		}
		return m.travel_not_modelled();
	}
</script>

<ul class="flex flex-col gap-2">
	{#each state.routes as choice (choice.profile)}
		{@const blocked = blockedText(choice)}
		{@const isSelected = choice.profile === state.selectedProfile && !blocked}
		<li>
			<button
				type="button"
				onclick={() => !blocked && (state.selectedProfile = choice.profile)}
				disabled={!!blocked}
				aria-current={isSelected}
				class="flex w-full items-center gap-3 rounded-md border px-3 py-2 text-start transition-colors {isSelected
					? 'border-foreground/40 bg-muted/60'
					: 'border-border/60'} {blocked ? 'opacity-50' : 'hover:bg-muted/40'}"
			>
				<span class="min-w-0 flex-1">
					<span class="block text-sm font-medium">{PROFILE_LABEL[choice.profile]()}</span>
					<span class="text-muted-foreground block truncate text-xs">
						{formatJulianDate(choice.route.departJd)} → {formatJulianDate(choice.route.arriveJd)}
					</span>
				</span>
				<span class="shrink-0 text-end">
					{#if blocked}
						<span class="text-muted-foreground block text-xs">{m.travel_out_of_reach()}</span>
						<span class="text-muted-foreground block text-[11px] tabular-nums">{blocked}</span>
					{:else}
						<span class="block text-sm font-semibold tabular-nums">
							{formatTripTime(choice.route.tofDays)}
						</span>
						<span class="text-muted-foreground block text-xs tabular-nums">
							{m.travel_unit_km_s({ value: choice.route.totalDvKms.toFixed(1) })}
						</span>
					{/if}
				</span>
			</button>
		</li>
	{/each}
</ul>
