<!--
  One trajectory: name and dates on the left, cost on the right, hazards on a
  line of their own beneath both. Shared by the list and the cruise box, so
  rows always match. A trip between stars that the two clocks read differently
  gives both durations on the right.

  The cost column tops out with the name rather than centring, which frees the
  hazard line to run the row's full width and carry a chip more.

  With no route yet, every line stays and fills with dashes, so the box
  holding the slider keeps its height.
-->
<script lang="ts">
	import { tick, untrack } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import MoveRightIcon from '@lucide/svelte/icons/move-right';
	import { formatJulianDate } from '$lib/format/date';
	import { formatDurationNarrow } from '$lib/format/duration';
	import { formatNumber } from '$lib/format/quantities';
	import {
		formatAcceleration,
		formatDvBrief,
		formatTripDate,
		shipDuration
	} from '$lib/travel/format';
	import { routeDurationDays, routeShipDays, type Route } from '$lib/math/travel';
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

	/** Roughly what "+9" and its gap take, charged against the line before the
	 *  last chip is allowed to stay. */
	const COUNT_WIDTH_PX = 34;
	/** `gap-2` between chips, in pixels. */
	const CHIP_GAP_PX = 8;

	let lineEl = $state<HTMLElement | null>(null);

	/**
	 * How many chips the line has room for, worst-first. Measured rather than
	 * fixed at three: the same row is a desktop panel's width and a phone's, and
	 * a chip cut mid-word reads as a broken figure rather than as more to come.
	 * Everything, until the measurement lands.
	 */
	let fits = $state(Number.POSITIVE_INFINITY);

	function howManyFit(line: HTMLElement): number {
		const chips = [...line.children] as HTMLElement[];
		const room = line.clientWidth;
		let used = 0;
		let n = 0;
		for (const chip of chips) {
			const next = used + (n === 0 ? 0 : CHIP_GAP_PX) + chip.offsetWidth;
			if (next > room) break;
			used = next;
			n += 1;
		}
		if (n === chips.length) return n;
		// Something was dropped, so the count that says so has to fit as well.
		while (n > 0 && used + CHIP_GAP_PX + COUNT_WIDTH_PX > room) {
			n -= 1;
			used -= chips[n].offsetWidth + (n === 0 ? 0 : CHIP_GAP_PX);
		}
		return n;
	}

	// Widths are read with every chip in place: a chip that is not rendered has
	// no width to measure. They are read after the DOM update and before the
	// paint, so the full line never shows. The line cannot grow with its contents
	// (see `min-w-0` below), so restoring them cannot resize it and set this off
	// again.
	$effect(() => {
		const line = lineEl;
		if (!line) return;
		void hazards;
		let run = 0;
		const measure = () => {
			const at = ++run;
			untrack(() => (fits = Number.POSITIVE_INFINITY));
			void tick().then(() => {
				if (at === run) untrack(() => (fits = howManyFit(line)));
			});
		};
		measure();
		const ro = new ResizeObserver(measure);
		ro.observe(line);
		return () => {
			ro.disconnect();
			run = -1;
		};
	});

	/** Drive strength for the two continuously-powered route kinds; null for
	 *  coasting ones. */
	let accel = $derived(route ? (route.constantThrust ?? route.lowThrust?.accelMs2 ?? null) : null);

	/** Everything the trip takes, on the Earth's clock. */
	let earthTime = $derived(route ? formatDurationNarrow(routeDurationDays(route)) : '');
	/** The ship's clock, on a trip between stars where it reads differently. */
	let shipTime = $derived(
		route?.interstellar ? shipDuration(routeDurationDays(route), routeShipDays(route)) : null
	);
	let dateBox = $derived(shipTime ? 'inline-block' : 'whitespace-nowrap');
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
		     explains duration on a spiral. When the name and the figure do not fit
		     on one line, the figure goes to the next line with its unit. -->
		<span class="flex flex-wrap items-baseline gap-x-1.5 text-sm font-medium">
			{routeLabel(profile)}{#if accel !== null}<span
					class="text-muted-foreground text-xs font-normal whitespace-nowrap tabular-nums"
					>{formatAcceleration(accel)}</span
				>{:else if via}<span class="text-muted-foreground text-xs font-normal"
					>{m.travel_via({ body: via })}</span
				>{/if}
		</span>
		<!-- The two clocks of a trip between stars give the cost column a third
		     line, so the dates can use two lines. Each date is then a box that
		     goes to the next line whole. Only a date wider than the column breaks
		     inside, at a space, so that no date is cut. -->
		<span
			class="text-muted-foreground block text-xs {shipTime
				? 'overflow-hidden text-ellipsis'
				: 'truncate'}"
		>
			{#if route}
				<span class={dateBox}>{formatJulianDate(route.departJd)}</span>
				<span class={dateBox}
					><MoveRightIcon
						class="inline size-[1em] align-[-0.125em] rtl:rotate-180"
						aria-hidden="true"
					/>
					{formatTripDate(route.arriveJd, route.departJd)}</span
				>
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
		{:else if route && shipTime}
			<span class="block text-sm font-semibold tabular-nums">
				{m.travel_clock_ship({ value: shipTime })}
			</span>
			<span class="text-muted-foreground block text-xs tabular-nums">
				{m.travel_clock_earth({ value: earthTime })}
			</span>
			<span class="text-muted-foreground block text-xs tabular-nums">
				{formatDvBrief(route.totalDvKms)}
			</span>
		{:else if route}
			<!-- Everything the trip takes, not only the crossing. A route that arrives
			     sooner and then aerobrakes for five months is not faster. -->
			<span class="block text-sm font-semibold tabular-nums">
				{earthTime}
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
		     not fit instead.

		     `min-w-0` keeps it out of the grid's column sizing: the chips are the
		     one thing on the row that must never decide how wide it is. -->
		<span
			bind:this={lineEl}
			class="col-start-2 col-end-4 row-start-2 mt-0.5 flex min-h-4 min-w-0 items-center gap-2 overflow-hidden text-[11px] whitespace-nowrap"
		>
			{#each hazards.slice(0, fits) as hazard (hazard.kind)}
				{@const Icon = hazardIcon(hazard)}
				<span class="flex shrink-0 items-center gap-1 {HAZARD_TEXT[hazard.severity]}">
					<Icon class="size-3 shrink-0" aria-hidden="true" />
					{hazardChip(hazard)}
				</span>
			{/each}
			{#if hazards.length > fits}
				<span class="text-muted-foreground shrink-0"
					>{m.travel_hazard_more({ count: formatNumber(hazards.length - fits) })}</span
				>
			{/if}
		</span>
	{/if}
</span>
