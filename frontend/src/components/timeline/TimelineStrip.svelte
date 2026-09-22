<!--
  The strip along the bottom of the map: a run of moments and stretches on the
  simulation clock, as cards over a scrubbable axis.

  It draws and it reports; what a pick means belongs to whoever owns the run —
  a trip frames the leg it names, a spacecraft only moves time. The clock is
  read here rather than passed in as a number, since the handle follows it at
  frame rate.
-->
<script lang="ts">
	import { untrack, type Snippet } from 'svelte';
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import PlayIcon from '@lucide/svelte/icons/play';
	import SquareIcon from '@lucide/svelte/icons/square';
	import XIcon from '@lucide/svelte/icons/x';
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
		/** Which item is the subject, when the host knows it. Several stops can
		 *  share a timestamp, and the clock alone cannot tell them apart. */
		activeId?: string;
		/** Stretches the map has nothing to draw at; greyed out on the axis. */
		gaps?: readonly TimelineSpan[];
		/** Where the strip sits; the map page's slot above the time bar unless
		 *  the host says otherwise. */
		positionClass?: string;
		/** Puts a button at the end of the header that takes the strip away. */
		onClose?: () => void;
		closeLabel?: string;
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
		activeId,
		gaps = [],
		onClose,
		closeLabel,
		positionClass = 'fixed bottom-[calc(var(--safe-bottom)_+_4.75rem)] end-[calc(var(--safe-end)_+_4.5rem)] start-[calc(var(--safe-start)_+_var(--detail-panel)_+_1rem)]'
	}: Props = $props();

	let startJd = $derived(items[0]?.startJd ?? 0);
	let endJd = $derived(items[items.length - 1]?.endJd ?? 0);
	let spanDays = $derived(endJd - startJd);
	let activeIndex = $derived.by(() => {
		const named = activeId === undefined ? -1 : items.findIndex((item) => item.id === activeId);
		return named >= 0 ? named : entryIndexAt(items, clock.jd);
	});
	let clockLabel = $derived(formatJulianDate(clock.jd));
	let ticks = $derived(spanDays > 0 ? axisTicks(startJd, endJd, 7) : []);

	const phases = $derived(items.filter((item) => item.isPhase));
	/** Moment marks, one per bucket across the track: a mark is under two
	 *  pixels wide, so thousands of them stack into the same ink as a few
	 *  hundred and only cost layout. */
	const MOMENT_BUCKETS = 400;
	const moments = $derived.by(() => {
		const seen = new Set<number>();
		const out: Array<{ id: string; at: number; note?: string }> = [];
		for (const item of items) {
			if (item.isPhase) continue;
			const at = fraction(item.startJd);
			const bucket = Math.round(at * MOMENT_BUCKETS);
			if (seen.has(bucket)) continue;
			seen.add(bucket);
			out.push({ id: item.id, at, note: item.note });
		}
		return out;
	});

	/** Where `jd` sits along the track, clamped: the clock is free to be years
	 *  off either end, and the handle should sit at the end it ran past. */
	function fraction(jd: number): number {
		if (!(spanDays > 0)) return 0;
		return Math.min(1, Math.max(0, (jd - startJd) / spanDays));
	}

	let clockFraction = $derived(fraction(clock.jd));

	let trackEl: HTMLButtonElement | undefined = $state();
	let cardsEl: HTMLOListElement | undefined = $state();
	let viewportEl = $state<HTMLElement | null>(null);
	let scrollX = $state(0);
	let viewportW = $state(0);

	/** A card's width and the gap after it, pixels — `min-w-[8rem]` and
	 *  `gap-2`. A run long enough to be windowed always overflows, so every
	 *  card sits at exactly this pitch and the window is arithmetic. */
	const CARD_PX = 128;
	const GAP_PX = 8;
	const PITCH_PX = CARD_PX + GAP_PX;
	/** Cards drawn past each edge, so a flick lands on something. */
	const OVERSCAN = 6;
	/** A traverse runs to thousands of stops; past this the row is windowed
	 *  rather than built whole. Below it every card is drawn, which is what
	 *  lets a short run stretch its cards across the strip. */
	const WINDOW_FROM = 40;

	const windowed = $derived(items.length > WINDOW_FROM);

	$effect(() => {
		const el = viewportEl;
		if (!el) return;
		const read = () => {
			// RTL scrolls to negative offsets; the window counts from the start
			// edge either way.
			scrollX = Math.abs(el.scrollLeft);
			viewportW = el.clientWidth;
		};
		read();
		el.addEventListener('scroll', read, { passive: true });
		const observer = new ResizeObserver(read);
		observer.observe(el);
		return () => {
			el.removeEventListener('scroll', read);
			observer.disconnect();
		};
	});

	/** The stretch of cards actually built, inclusive. */
	const range = $derived.by(() => {
		if (!windowed) return { first: 0, last: items.length - 1 };
		return {
			first: Math.max(0, Math.floor(scrollX / PITCH_PX) - OVERSCAN),
			last: Math.min(items.length - 1, Math.ceil((scrollX + viewportW) / PITCH_PX) + OVERSCAN)
		};
	});
	const visible = $derived(windowed ? items.slice(range.first, range.last + 1) : items);

	// A record of twenty events is wider than the strip, so the row scrolls and
	// the card the clock is on is kept in view. A short run never overflows and
	// nothing scrolls. The scroll position is not a dependency: this follows
	// the clock, and reading it would fight the reader's own scrolling.
	$effect(() => {
		const index = activeIndex;
		const el = viewportEl;
		if (index < 0 || !el) return;
		if (!windowed) {
			cardsEl?.children[index]?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
			return;
		}
		const from = untrack(() => scrollX);
		const left = index * PITCH_PX;
		let to = from;
		if (left < from) to = left;
		else if (left + CARD_PX > from + el.clientWidth) to = left + CARD_PX - el.clientWidth;
		if (to !== from) el.scrollLeft = getComputedStyle(el).direction === 'rtl' ? -to : to;
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
	class="border-border/60 bg-background/90 z-10 hidden
		flex-col gap-2.5 rounded-xl border p-3 shadow-lg backdrop-blur md:flex {positionClass}"
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
			{#if onClose}
				<button
					type="button"
					class="hover:bg-muted ms-1 inline-flex size-7 items-center justify-center rounded-md transition-colors"
					onclick={onClose}
					aria-label={closeLabel}
					title={closeLabel}
				>
					<XIcon class="size-4" />
				</button>
			{/if}
		</div>
	</div>

	{#snippet card(item: StripItem, index: number, props: Record<string, unknown>)}
		{@const active = index === activeIndex}
		<svelte:element
			this={item.href ? 'a' : 'button'}
			href={item.href}
			type={item.href ? undefined : 'button'}
			{...props}
			onclick={() => onPick(index)}
			aria-current={active ? 'true' : undefined}
			class="flex min-w-0 flex-1 flex-col items-start gap-0.5 rounded-lg border px-2.5 py-2 text-start transition-colors
				{active ? 'border-border bg-muted' : 'hover:bg-muted/50 border-transparent'}"
		>
			{#if item.image}
				<!-- `w-0 min-w-full`: the row is sized to its content, so a loaded
				     image's natural width would widen every card and grow the whole
				     strip. The height is the 3:1 box at the card's minimum width
				     rather than an aspect ratio, so a record of one card stretched
				     across the viewer stays as tall as a record of fifty. -->
				<img
					src={item.image}
					alt=""
					loading="lazy"
					class="mb-1 h-[calc(8rem/3)] w-0 min-w-full rounded object-cover"
				/>
			{/if}
			<span class="flex w-full min-w-0 items-center gap-1.5">
				<!-- A phase is a stretch of the bar below and wears its colour; a
				     moment is a point on it and has none of its own. -->
				{#if item.isPhase && item.color}
					<span class="size-1.5 shrink-0 rounded-full" style="background: {item.color}"></span>
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
		</svelte:element>
	{/snippet}

	<!-- A windowed row draws only cards the reader can reach, so the card is
	     fixed at its own width; an unwindowed one lets a short run stretch
	     across the strip. The tooltip is built only where there is a hint to
	     show: one per card costs more than every card it annotates. -->
	{#snippet cell(item: StripItem, index: number)}
		<li class="flex {windowed ? 'w-32 shrink-0' : 'min-w-[8rem] flex-1'}">
			{#if item.note}
				<Tooltip.Root>
					<Tooltip.Trigger>
						{#snippet child({ props })}
							{@render card(item, index, props)}
						{/snippet}
					</Tooltip.Trigger>
					<Tooltip.Content>{item.note}</Tooltip.Content>
				</Tooltip.Root>
			{:else}
				{@render card(item, index, {})}
			{/if}
		</li>
	{/snippet}

	<!-- A record of twenty events is wider than the strip. `min-w-full` keeps a
	     short run filling it, `w-max` lets a long one run past and scroll. The
	     spacers stand in for the cards outside the window, so the row keeps its
	     full width and the scrollbar its meaning. -->
	<ScrollArea orientation="horizontal" scrollbarXClasses="h-1.5" bind:viewportRef={viewportEl}>
		<ol bind:this={cardsEl} class="flex w-max min-w-full items-stretch gap-2 pb-1.5">
			{#if windowed && range.first > 0}
				<li
					aria-hidden="true"
					class="shrink-0"
					style="width: {range.first * PITCH_PX - GAP_PX}px"
				></li>
			{/if}
			{#each visible as item, offset (item.id)}
				{@render cell(item, range.first + offset)}
			{/each}
			{#if windowed && range.last < items.length - 1}
				<li
					aria-hidden="true"
					class="shrink-0"
					style="width: {(items.length - 1 - range.last) * PITCH_PX - GAP_PX}px"
				></li>
			{/if}
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
				{#each phases as item (item.id)}
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
				{/each}
				<!-- Moments: what happens at a point rather than over one. -->
				{#each moments as moment (moment.id)}
					<span
						class="bg-muted-foreground ring-background absolute top-1/2 z-[2] size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-1 {moment.note
							? 'opacity-40'
							: ''}"
						style="inset-inline-start: {moment.at * 100}%"
					></span>
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
