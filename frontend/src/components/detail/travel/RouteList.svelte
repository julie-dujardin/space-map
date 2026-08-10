<!--
  One family of trajectory as one line each: what it is and when it runs on the
  left, what it costs on the right. Picking one is what opens it — this is the
  first of the panel's two steps, and every row here is a way into the second.

  A route the chosen craft cannot fly stays visible and goes quiet, with the
  reason in place of its figures — hiding it would leave the panel silently
  short of options.

  A window picked off the porkchop by hand comes last, as an addition to the
  three the solver offers rather than one of them. Its row is there before it is:
  an empty fourth option is what makes the field below look like a choice.

  A swing-by names the body it goes past, since that and its dates are the only
  things separating it from the routes above.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import { formatJulianDate } from '$lib/format/date';
	import { formatQuantity } from '$lib/format/quantities';
	import type { OfferedRoute, TravelPanelState } from '$lib/travel/panel.svelte';
	import { formatDurationNarrow } from '$lib/format/duration';
	import { formatAcceleration, formatDvBrief } from '$lib/travel/format';
	import { routeDurationDays, type Route } from '$lib/math/travel';
	import { routesIn, type RouteFamily } from '$lib/travel/route-families';
	import { departureNote } from './vehicle-labels';
	import { routeLabel } from './route-labels';

	interface Props {
		state: TravelPanelState;
		/** Which family is being read; the tabs above choose it. */
		family: RouteFamily | null;
		/** What to call the body a swing-by passes. */
		nameOf?: (id: string) => string;
		/** Send the reader to the field they pick a custom window on. Absent leaves
		 *  the fourth row out — there is nowhere for it to point. */
		onFocusField?: (() => void) | null;
	}
	let { state, family, nameOf = (id: string) => id, onFocusField = null }: Props = $props();

	let shown = $derived(routesIn(state.offered, family));

	/** How hard a route's drive pushes, on the two kinds flown under power the
	 *  whole way; null on the ones that coast. */
	function driveAccel(route: Route): number | null {
		return route.constantThrust ?? route.lowThrust?.accelMs2 ?? null;
	}

	/** The body a route goes past, named, or null when it goes straight there. */
	function via(choice: OfferedRoute): string | null {
		const pass = choice.route.flybys?.[0];
		return pass ? nameOf(pass.bodyId) : null;
	}

	interface Blocked {
		header: string;
		detail: string;
	}

	function blockedText(choice: OfferedRoute): Blocked | null {
		const result = state.feasibility(choice.route);
		if (!result || result.status === 'ok') return null;
		const out = (detail: string) => ({ header: m.travel_out_of_reach(), detail });
		// "Out of reach" is a claim about the vehicle; these three are refusals
		// to judge it — a missing figure, a curve whose source stopped early, a
		// drive the impulsive model cannot price — and say so instead.
		const unjudged = (detail: string) => ({ header: m.travel_unjudged(), detail });
		if (result.status === 'over-c3') {
			return out(m.travel_needs_c3({ value: choice.route.c3Km2S2.toFixed(0) }));
		}
		if (result.status === 'insufficient-dv') {
			return out(m.travel_needs_dv({ value: choice.route.inSpaceDvKms.toFixed(1) }));
		}
		// The craft and the trip disagree about where it starts, which is a
		// statement about the craft rather than about this particular route.
		if (result.status === 'wrong-departure' && state.vehicle) {
			return out(departureNote(state.vehicle));
		}
		// Also about the craft rather than the route: it is being asked to fly
		// through an atmosphere with nothing published that it could do it behind.
		if (result.status === 'no-aeroshell') {
			return out(m.travel_no_aeroshell());
		}
		// A launcher's payload is what it can send to *this* energy, so the same
		// cargo clears one trajectory and not the next.
		if (result.status === 'over-payload' && result.payloadKg !== undefined) {
			return out(
				m.travel_lifts({
					value: formatQuantity({ value: result.payloadKg, unit: 'kilogram' }, true)
				})
			);
		}
		if (result.status === 'unknown') {
			return unjudged(m.travel_no_published_figure());
		}
		if (result.status === 'beyond-published') {
			const end = state.vehicle?.c3Curve?.points.at(-1)?.[0];
			return unjudged(
				end === undefined
					? m.travel_no_published_figure()
					: m.travel_past_published({ value: end.toFixed(0) })
			);
		}
		// The last one left: a drive that cannot make an impulsive burn, faced with
		// a trajectory built out of two of them. It has a row of its own further up
		// the list, so this says which fact is in the way rather than only that one
		// is.
		return unjudged(m.travel_thrust_too_low());
	}
</script>

<ul class="flex flex-col gap-2">
	{#each shown as choice (choice.profile)}
		{@const blocked = blockedText(choice)}
		{@const viaName = via(choice)}
		<li>
			<button
				type="button"
				onclick={() => !blocked && state.choose(choice.profile)}
				disabled={!!blocked}
				class="border-border/60 flex w-full items-center gap-3 rounded-md border px-3 py-2 text-start transition-colors {blocked
					? 'opacity-50'
					: 'hover:bg-muted/40'}"
			>
				<span class="min-w-0 flex-1">
					<!-- The acceleration rides on the name because it is what tells one
					     powered route from another: the dates below say the same thing
					     whatever the drive, and this is the only thing that does not. On
					     a spiral it is also the whole explanation of the duration. -->
					<span class="block text-sm font-medium">
						{routeLabel(choice.profile)}{#if driveAccel(choice.route) !== null}<span
								class="text-muted-foreground ms-1.5 text-xs font-normal tabular-nums"
								>{formatAcceleration(driveAccel(choice.route) ?? 0)}</span
							>{:else if viaName}<span class="text-muted-foreground ms-1.5 text-xs font-normal"
								>{m.travel_via({ body: viaName })}</span
							>{/if}
					</span>
					<span class="text-muted-foreground block truncate text-xs">
						{formatJulianDate(choice.route.departJd)} → {formatJulianDate(choice.route.arriveJd)}
					</span>
				</span>
				<span class="shrink-0 text-end">
					{#if blocked}
						<span class="text-muted-foreground block text-xs">{blocked.header}</span>
						<span class="text-muted-foreground block text-[11px] tabular-nums"
							>{blocked.detail}</span
						>
					{:else}
						<!-- Everything the trip takes, not just the crossing. A route that
						     arrives sooner and then spends five months aerobraking into the
						     orbit that was asked for is not the faster route, and this is
						     the column that decision is made in. -->
						<span class="block text-sm font-semibold tabular-nums">
							{formatDurationNarrow(routeDurationDays(choice.route))}
						</span>
						<span class="text-muted-foreground block text-xs tabular-nums">
							{formatDvBrief(choice.route.totalDvKms)}
						</span>
					{/if}
				</span>
				<!-- A row that can be flown leads somewhere; one that cannot has already
				     said everything it has to say. -->
				{#if !blocked}
					<ChevronRightIcon class="text-muted-foreground size-4 shrink-0 rtl:rotate-180" />
				{/if}
			</button>
		</li>
	{/each}

	{#if family === 'transfer' && onFocusField && state.grid && !state.custom}
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
					<span class="block text-sm font-medium">{routeLabel('custom')}</span>
					<span class="text-muted-foreground block truncate text-xs">
						{m.travel_windows_pick_prompt()}
					</span>
				</span>
			</button>
		</li>
	{/if}
</ul>
