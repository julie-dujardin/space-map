<!--
  One trajectory: name and dates on the left, cost on the right, hazards on a
  line of their own beneath both. Shared by the list and the cruise box, so
  rows always match.

  The cost column tops out with the name rather than centring, which frees the
  hazard line to run the row's full width and carry a chip more.

  With no route yet, every line stays and fills with dashes, so the box
  holding the slider keeps its height.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import MoveRightIcon from '@lucide/svelte/icons/move-right';
	import { formatJulianDate } from '$lib/format/date';
	import { formatDurationNarrow } from '$lib/format/duration';
	import { formatAcceleration, formatDvBrief } from '$lib/travel/format';
	import { routeDurationDays, type Route } from '$lib/math/travel';
	import type { Hazard } from '$lib/travel/hazards';
	import { hazardChip } from '$lib/travel/hazard-labels';
	import type { RouteOption } from '$lib/travel/trip';
	import { routeLabel } from './route-labels';
	import { routeMark } from './route-tier';
	import type { Blocked } from './route-blocked';
	import { hazardIcon, HAZARD_TEXT } from './hazard-style';

	interface Props {
		profile: RouteOption;
		/** The trajectory, or null where there is a row before there is one. */
		route: Route | null;
		/** What it puts the craft through. Empty until the scan lands. */
		hazards?: readonly Hazard[];
		/** Why the chosen craft cannot fly it, in place of its figures. */
		blocked?: Blocked | null;
		/** The body it goes past, named, on the one kind that does. */
		via?: string | null;
		/** What to say instead of dates before there is a route: how to get one. */
		hint?: string | null;
		/** Keeps the chip line's height even when there are no chips. */
		reserveHazards?: boolean;
	}
	let {
		profile,
		route,
		hazards = [],
		blocked = null,
		via = null,
		hint = null,
		reserveHazards = false
	}: Props = $props();

	/** The colour this trajectory carries everywhere else in the panel. */
	let mark = $derived(routeMark(profile));

	/** Chips arrive worst-first; this is how many fit before the mildest drop.
	 *  Three is what the panel's width holds in full — a fourth is cut mid-word
	 *  more often than not, which reads as a broken figure rather than as more. */
	const CHIP_LIMIT = 3;

	/** Drive strength for the two continuously-powered route kinds; null for
	 *  coasting ones. */
	let accel = $derived(route ? (route.constantThrust ?? route.lowThrust?.accelMs2 ?? null) : null);
</script>

<span class="grid w-full grid-cols-[auto_1fr_auto_auto] items-start gap-x-3">
	<!-- A column of its own rather than sitting in the name: the marks then line
	     up down the list whatever each route is called. Kept even when there is
	     no mark, so a family without one indents like every other. -->
	<span
		class="{mark ?? ''} col-start-1 row-span-2 row-start-1 size-2 self-center rounded-full"
		aria-hidden="true"
	></span>

	<span class="col-start-2 row-start-1 min-w-0">
		<!-- Acceleration sits by the name: it separates two powered routes, and
		     explains duration on a spiral. -->
		<span class="block text-sm font-medium">
			{routeLabel(profile)}{#if accel !== null}<span
					class="text-muted-foreground ms-1.5 text-xs font-normal tabular-nums"
					>{formatAcceleration(accel)}</span
				>{:else if via}<span class="text-muted-foreground ms-1.5 text-xs font-normal"
					>{m.travel_via({ body: via })}</span
				>{/if}
		</span>
		<span class="text-muted-foreground block truncate text-xs">
			{#if route}
				{formatJulianDate(route.departJd)}
				<MoveRightIcon
					class="inline size-[1em] align-[-0.125em] rtl:rotate-180"
					aria-hidden="true"
				/>
				{formatJulianDate(route.arriveJd)}
			{:else if hint}
				{hint}
			{:else}
				&mdash;
			{/if}
		</span>
	</span>

	<span class="col-start-3 row-start-1 shrink-0 text-end">
		{#if blocked}
			<span class="text-muted-foreground block text-xs">{blocked.header}</span>
			<span class="text-muted-foreground block text-[11px] tabular-nums">{blocked.detail}</span>
		{:else if route}
			<!-- Everything the trip takes, not only the crossing. A route that arrives
			     sooner and then aerobrakes for five months is not faster. -->
			<span class="block text-sm font-semibold tabular-nums">
				{formatDurationNarrow(routeDurationDays(route))}
			</span>
			<span class="text-muted-foreground block text-xs tabular-nums">
				{formatDvBrief(route.totalDvKms)}
			</span>
		{:else}
			<span class="text-muted-foreground block text-sm font-semibold">&mdash;</span>
			<span class="text-muted-foreground block text-xs">&mdash;</span>
		{/if}
	</span>

	<!-- Only a row you can open shows the chevron. -->
	{#if route && !blocked}
		<ChevronRightIcon
			class="text-muted-foreground col-start-4 row-span-2 row-start-1 size-4 shrink-0 self-center rtl:rotate-180"
			aria-hidden="true"
		/>
	{/if}

	{#if hazards.length > 0 || reserveHazards}
		<!-- One line, never wrapped, running under the cost column but stopping
		     short of the chevron, which is centred on the whole row. A line that
		     grows pushes the next trajectory off the screen, so count what does
		     not fit instead. -->
		<span
			class="col-start-2 col-end-4 row-start-2 mt-0.5 flex min-h-4 items-center gap-2 overflow-hidden text-[11px] whitespace-nowrap"
		>
			{#each hazards.slice(0, CHIP_LIMIT) as hazard (hazard.kind)}
				{@const Icon = hazardIcon(hazard)}
				<span class="flex items-center gap-1 {HAZARD_TEXT[hazard.severity]}">
					<Icon class="size-3 shrink-0" aria-hidden="true" />
					{hazardChip(hazard)}
				</span>
			{/each}
			{#if hazards.length > CHIP_LIMIT}
				<span class="text-muted-foreground"
					>{m.travel_hazard_more({ count: hazards.length - CHIP_LIMIT })}</span
				>
			{/if}
		</span>
	{/if}
</span>
