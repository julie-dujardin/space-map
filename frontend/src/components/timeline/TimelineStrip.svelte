<!--
  The strip along the bottom of the map: a run of moments and stretches on the
  simulation clock, as cards over a scrubbable axis.

  It draws and it reports; what a pick means belongs to whoever owns the run —
  a trip frames the leg it names, a spacecraft only moves time. The clock is
  read here rather than passed in as a number, since the handle follows it at
  frame rate.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import PlayIcon from '@lucide/svelte/icons/play';
	import SquareIcon from '@lucide/svelte/icons/square';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { formatJulianDate } from '$lib/format/date';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { getSettings } from '$lib/state/settings.svelte';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { axisTicks, entryIndexAt, type AxisTick, type TimelineSpan } from '$lib/timeline/axis';
	import type { StripItem } from '$lib/timeline/strip';

	interface Props {
		items: readonly StripItem[];
		/** What this is a timeline of, drawn at the top left. */
		title: Snippet;
		clock: SimClock;
		/** Card `index` was pressed. */
		onPick: (index: number) => void;
		/** The axis was scrubbed to `jd`. */
		onScrub: (jd: number) => void;
		playing: boolean;
		onTogglePlay: () => void;
		/** What playing this particular run is called — flying a trip and flying a
		 *  mission are not the same act. */
		playLabel: string;
		/** Move `delta` items along from where the clock stands. */
		onStep: (delta: number) => void;
		/** Stretches the map has nothing to draw at; greyed out on the axis. */
		gaps?: readonly TimelineSpan[];
	}

	let {
		items,
		title,
		clock,
		onPick,
		onScrub,
		playing,
		onTogglePlay,
		playLabel,
		onStep,
		gaps = []
	}: Props = $props();

	let startJd = $derived(items[0]?.startJd ?? 0);
	let endJd = $derived(items[items.length - 1]?.endJd ?? 0);
	let spanDays = $derived(endJd - startJd);
	let activeIndex = $derived(entryIndexAt(items, clock.jd));
	let clockLabel = $derived(formatJulianDate(clock.jd));
	let ticks = $derived(spanDays > 0 ? axisTicks(startJd, endJd, 7) : []);

	/** Where `jd` sits along the track, clamped: the clock is free to be years
	 *  off either end, and the handle should sit at the end it ran past. */
	function fraction(jd: number): number {
		if (!(spanDays > 0)) return 0;
		return Math.min(1, Math.max(0, (jd - startJd) / spanDays));
	}

	let clockFraction = $derived(fraction(clock.jd));

	let trackEl: HTMLButtonElement | undefined = $state();
	let cardsEl: HTMLOListElement | undefined = $state();

	// A record of twenty events is wider than the strip, so the row scrolls and
	// the card the clock is on is kept in view. A short run never overflows and
	// nothing scrolls.
	$effect(() => {
		const card = cardsEl?.children[activeIndex];
		card?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
	});

	function scrubToFraction(f: number): void {
		onScrub(startJd + spanDays * Math.min(1, Math.max(0, f)));
	}

	function fractionFromClientX(clientX: number): number {
		if (!trackEl) return 0;
		const rect = trackEl.getBoundingClientRect();
		let f = (clientX - rect.left) / rect.width;
		if (getComputedStyle(trackEl).direction === 'rtl') f = 1 - f;
		return f;
	}

	function startScrub(e: PointerEvent): void {
		e.preventDefault();
		scrubToFraction(fractionFromClientX(e.clientX));
		const move = (ev: PointerEvent) => scrubToFraction(fractionFromClientX(ev.clientX));
		const up = () => {
			window.removeEventListener('pointermove', move);
			window.removeEventListener('pointerup', up);
			window.removeEventListener('pointercancel', up);
		};
		window.addEventListener('pointermove', move);
		window.addEventListener('pointerup', up);
		window.addEventListener('pointercancel', up);
	}

	function onTrackKey(e: KeyboardEvent): void {
		const nudge = e.shiftKey ? 0.1 : 0.02;
		if (e.key === 'ArrowRight' || e.key === 'ArrowUp') scrubToFraction(clockFraction + nudge);
		else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') scrubToFraction(clockFraction - nudge);
		else if (e.key === 'Home') scrubToFraction(0);
		else if (e.key === 'End') scrubToFraction(1);
		else return;
		e.preventDefault();
	}

	/**
	 * Ticks sit on calendar boundaries, so each says only what its boundary is:
	 * the bare year on New Year, the month on the first of it. Formatted
	 * straight off Intl rather than the app's date helpers, which answer with a
	 * whole date — unreadable at this size.
	 */
	function tickLabel(tick: AxisTick): string {
		const date = tick.date;
		switch (tick.unit) {
			case 'year':
				// Not through Intl: a year is a label here, not a quantity, and
				// grouping it reads as "2,035".
				return String(date.getFullYear());
			case 'month':
				return date.toLocaleString(getLocale(), { month: 'short' });
			case 'day':
				return date.toLocaleString(getLocale(), { month: 'short', day: 'numeric' });
			case 'hour':
				return date.toLocaleString(getLocale(), {
					hour: '2-digit',
					minute: '2-digit',
					hour12: getSettings().resolvedHour12
				});
		}
	}
</script>

<div
	class="border-border/60 bg-background/90 pointer-events-auto fixed bottom-[calc(var(--safe-bottom)_+_4.75rem)] z-10 hidden
		flex-col gap-2.5 rounded-xl border p-3 shadow-lg backdrop-blur
		end-[calc(var(--safe-end)_+_4.5rem)] start-[calc(var(--safe-start)_+_var(--detail-panel)_+_1rem)] md:flex"
>
	<div class="flex items-center justify-between gap-3">
		<h2 class="min-w-0 truncate text-sm font-medium">{@render title()}</h2>
		<div class="flex shrink-0 items-center gap-1">
			<span class="text-muted-foreground me-1 text-xs tabular-nums">
				{clockLabel}
			</span>
			<button
				type="button"
				class="hover:bg-muted inline-flex size-7 items-center justify-center rounded-md transition-colors"
				onclick={() => onStep(-1)}
				aria-label={m.timeline_prev()}
				title={m.timeline_prev()}
			>
				<ChevronLeftIcon class="size-4 rtl:rotate-180" />
			</button>
			<button
				type="button"
				class="hover:bg-muted inline-flex size-7 items-center justify-center rounded-md transition-colors"
				onclick={onTogglePlay}
				aria-label={playing ? m.timeline_stop() : playLabel}
				title={playing ? m.timeline_stop() : playLabel}
			>
				{#if playing}
					<SquareIcon class="size-3.5 fill-current" />
				{:else}
					<PlayIcon class="size-4 rtl:rotate-180" />
				{/if}
			</button>
			<button
				type="button"
				class="hover:bg-muted inline-flex size-7 items-center justify-center rounded-md transition-colors"
				onclick={() => onStep(1)}
				aria-label={m.timeline_next()}
				title={m.timeline_next()}
			>
				<ChevronRightIcon class="size-4 rtl:rotate-180" />
			</button>
		</div>
	</div>

	<!-- A record of twenty events is wider than the strip. `min-w-full` keeps a
	     short run filling it, `w-max` lets a long one run past and scroll. -->
	<ScrollArea orientation="horizontal" scrollbarXClasses="h-1.5">
		<ol bind:this={cardsEl} class="flex w-max min-w-full items-stretch gap-2 pb-1.5">
			{#each items as item, index (item.id)}
				{@const active = index === activeIndex}
				<li class="flex min-w-[8rem] flex-1">
					<Tooltip.Root disabled={!item.note}>
						<Tooltip.Trigger>
							{#snippet child({ props })}
								<button
									type="button"
									{...props}
									onclick={() => onPick(index)}
									aria-current={active ? 'true' : undefined}
									class="flex min-w-0 flex-1 flex-col items-start gap-0.5 rounded-lg border px-2.5 py-2 text-start transition-colors
										{active ? 'border-border bg-muted' : 'hover:bg-muted/50 border-transparent'}"
								>
									<span class="flex w-full min-w-0 items-center gap-1.5">
										<!-- A phase is a stretch of the bar below and wears its colour; a
										     moment is a point on it and has none of its own. -->
										{#if item.isPhase && item.color}
											<span class="size-1.5 shrink-0 rounded-full" style="background: {item.color}"
											></span>
										{/if}
										<span class="min-w-0 truncate text-sm {active ? 'font-medium' : ''}">
											{item.label}
										</span>
									</span>
									<span class="text-muted-foreground w-full truncate text-xs tabular-nums">
										{item.when}
									</span>
									{#if item.detail}
										<span class="text-muted-subtle w-full truncate text-[11px] tabular-nums">
											{item.detail}
										</span>
									{/if}
								</button>
							{/snippet}
						</Tooltip.Trigger>
						<Tooltip.Content>{item.note}</Tooltip.Content>
					</Tooltip.Root>
				</li>
			{/each}
		</ol>
	</ScrollArea>

	{#if spanDays > 0}
		<div class="relative h-9 px-1">
			<button
				type="button"
				bind:this={trackEl}
				role="slider"
				aria-label={m.timeline_scrub()}
				aria-valuemin={0}
				aria-valuemax={Math.round(spanDays)}
				aria-valuenow={Math.round(clockFraction * spanDays)}
				aria-valuetext={clockLabel}
				onpointerdown={startScrub}
				onkeydown={onTrackKey}
				class="focus-visible:ring-ring absolute inset-x-0 top-0 h-4 cursor-pointer rounded-full focus-visible:ring-2 focus-visible:outline-none"
			>
				<span class="bg-border absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full"></span>
				<!-- Gaps: where the run says something happened and the map has no
				     craft to show it — hatched, over the phases, under the marks. -->
				{#each gaps as gap, i (i)}
					{@const from = fraction(gap.startJd)}
					{@const to = fraction(gap.endJd)}
					{#if to > from}
						<span
							class="timeline-gap absolute top-1/2 z-[1] h-2.5 -translate-y-1/2 rounded-sm"
							title={m.timeline_gap()}
							style="inset-inline-start: {from * 100}%; width: {(to - from) * 100}%"
						></span>
					{/if}
				{/each}
				<!-- Phases: the stretches of the run, each the colour its arc is drawn
				     in. Laid down twice, so the part already past reads solid against
				     the part still ahead. -->
				{#each items as item (item.id)}
					{#if item.isPhase}
						{@const from = fraction(item.startJd)}
						{@const to = fraction(item.endJd)}
						{@const color = item.color ?? 'currentColor'}
						<span
							class="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full opacity-30"
							style="inset-inline-start: {from * 100}%; width: {(to - from) *
								100}%; background: {color}"
						></span>
						{#if clockFraction > from}
							<span
								class="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full"
								style="inset-inline-start: {from * 100}%; width: {(Math.min(clockFraction, to) -
									from) *
									100}%; background: {color}"
							></span>
						{/if}
					{/if}
				{/each}
				<!-- Moments: what happens at a point rather than over one. -->
				{#each items as item (item.id)}
					{#if !item.isPhase}
						<span
							class="bg-muted-foreground ring-background absolute top-1/2 z-[2] size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-1 {item.note
								? 'opacity-40'
								: ''}"
							style="inset-inline-start: {fraction(item.startJd) * 100}%"
						></span>
					{/if}
				{/each}
				<span
					class="bg-foreground ring-background absolute top-1/2 z-[3] size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2"
					style="inset-inline-start: {clockFraction * 100}%"
				></span>
			</button>
			{#each ticks as tick (tick.jd)}
				<span
					class="text-muted-subtle absolute top-4 -translate-x-1/2 text-[10px] whitespace-nowrap tabular-nums"
					style="inset-inline-start: {fraction(tick.jd) * 100}%"
				>
					{tickLabel(tick)}
				</span>
			{/each}
		</div>
	{/if}
</div>

<style>
	/* Hatched so it reads as "nothing here" next to the solid phase colours,
	   and stays legible over any of them. */
	.timeline-gap {
		background: repeating-linear-gradient(
			-45deg,
			color-mix(in oklch, var(--muted-foreground) 45%, transparent) 0 2px,
			color-mix(in oklch, var(--background) 70%, transparent) 2px 5px
		);
	}
</style>
