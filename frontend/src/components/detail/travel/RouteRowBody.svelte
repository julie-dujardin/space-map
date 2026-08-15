<!--
  One trajectory on one line: what it is and when it runs on the left, what it
  costs on the right. The list and the cruise box share it, so that one row
  cannot start to read differently from the other.

  With no route behind it, the row keeps every line and fills them with dashes.
  This holds the height of the box that carries the slider.
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
		/** What to say in place of the dates while there is no route: how to get
		 *  one. */
		hint?: string | null;
		/** Keep the chip line's height. A row with no chips stays as tall as one
		 *  with chips. */
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

	/** As many chips as fit a narrow row. They arrive worst first, so the mildest
	 *  are dropped. */
	const CHIP_LIMIT = 3;

	/** How hard a route's drive pushes, on the two kinds flown under power the
	 *  whole way; null on the ones that coast. */
	let accel = $derived(route ? (route.constantThrust ?? route.lowThrust?.accelMs2 ?? null) : null);
</script>

<span class="min-w-0 flex-1">
	<!-- The acceleration goes on the name. It is the only figure that separates
	     two powered routes, and on a spiral it explains the duration. The dot
	     before it repeats the colour this trajectory is marked with. -->
	<span class="block text-sm font-medium">
		{#if mark}<span
				class="{mark} me-1.5 inline-block size-2 rounded-full align-[0.1em]"
				aria-hidden="true"
			></span>{/if}{routeLabel(profile)}{#if accel !== null}<span
				class="text-muted-foreground ms-1.5 text-xs font-normal tabular-nums"
				>{formatAcceleration(accel)}</span
			>{:else if via}<span class="text-muted-foreground ms-1.5 text-xs font-normal"
				>{m.travel_via({ body: via })}</span
			>{/if}
	</span>
	<span class="text-muted-foreground block truncate text-xs">
		{#if route}
			{formatJulianDate(route.departJd)}
			<MoveRightIcon class="inline size-[1em] align-[-0.125em] rtl:rotate-180" aria-hidden="true" />
			{formatJulianDate(route.arriveJd)}
		{:else if hint}
			{hint}
		{:else}
			&mdash;
		{/if}
	</span>
	{#if hazards.length > 0 || reserveHazards}
		<!-- One line, never wrapped. A line that grows pushes the next trajectory
		     off the screen. Count what does not fit. -->
		<span
			class="mt-0.5 flex min-h-4 items-center gap-2 overflow-hidden text-[11px] whitespace-nowrap"
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
<span class="shrink-0 text-end">
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
		class="text-muted-foreground size-4 shrink-0 rtl:rotate-180"
		aria-hidden="true"
	/>
{/if}
