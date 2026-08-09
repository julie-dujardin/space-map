<!--
  The trajectories as one line each: what it is and when it runs on the left,
  what it costs on the right.

  A route the chosen craft cannot fly stays visible and goes quiet, with the
  reason in place of its figures — hiding it would leave the panel silently
  short of options.

  A window picked off the porkchop by hand comes last, as an addition to the
  three the solver offers rather than one of them. Its row is there before it is:
  an empty fourth option is what makes the field below look like a choice.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { formatJulianDate } from '$lib/format/date';
	import { formatQuantity } from '$lib/format/quantities';
	import type { OfferedRoute, RouteOption, TravelPanelState } from '$lib/travel/panel.svelte';
	import { formatAcceleration, formatTripTime } from '$lib/travel/format';
	import { departureNote } from './vehicle-labels';

	interface Props {
		state: TravelPanelState;
		/** Send the reader to the field they pick a custom window on. Absent leaves
		 *  the fourth row out — there is nowhere for it to point. */
		onFocusField?: (() => void) | null;
	}
	let { state, onFocusField = null }: Props = $props();

	const PROFILE_LABEL: Record<RouteOption, () => string> = {
		fast: m.travel_profile_fast,
		balanced: m.travel_profile_balanced,
		efficient: m.travel_profile_efficient,
		custom: m.travel_profile_custom,
		'constant-thrust': m.travel_profile_constant_thrust
	};

	function blockedText(choice: OfferedRoute): string | null {
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
	{#each state.offered as choice (choice.profile)}
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
					<!-- The acceleration rides on the name because it is what tells one
					     constant-thrust arc from another: the dates below say the same
					     thing whatever the drive, and this is the only thing that does
					     not. -->
					<span class="block text-sm font-medium">
						{PROFILE_LABEL[choice.profile]()}{#if choice.route.constantThrust}<span
								class="text-muted-foreground ms-1.5 text-xs font-normal tabular-nums"
								>{formatAcceleration(choice.route.constantThrust)}</span
							>{/if}
					</span>
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

	{#if onFocusField && state.grid && !state.custom}
		<!-- The fourth option before it has anything in it: a row rather than
		     nothing, so the field below reads as a way to choose rather than as a
		     picture of the three above. -->
		<li>
			<button
				type="button"
				onclick={onFocusField}
				class="border-border/60 hover:bg-muted/40 flex w-full items-center gap-3 rounded-md border border-dashed px-3 py-2 text-start transition-colors"
			>
				<span class="min-w-0 flex-1">
					<span class="block text-sm font-medium">{m.travel_profile_custom()}</span>
					<span class="text-muted-foreground block truncate text-xs">
						{m.travel_windows_pick_prompt()}
					</span>
				</span>
			</button>
		</li>
	{/if}
</ul>
