<!--
  The trip along the bottom of the map: every leg of the chosen trajectory, in
  order, against the clock the scene is drawn at. Picking one moves the
  simulation and camera to it, but never the *departure* — when the trip
  leaves is the planner's term, not this widget's.
-->
<script lang="ts">
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import MoveRightIcon from '@lucide/svelte/icons/move-right';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import PlayIcon from '@lucide/svelte/icons/play';
	import SquareIcon from '@lucide/svelte/icons/square';
	import * as m from '$lib/paraglide/messages.js';
	import { formatJulianDate } from '$lib/format/date';
	import { pathViewpoint, type TrajectoryPath } from '$lib/math/travel/path';
	import { craftPositionAt } from '$lib/math/travel/path-sample';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { getSettings } from '$lib/state/settings.svelte';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { PHASE_COLORS } from '$lib/travel/arc-colors';
	import { TripPlayback } from '$lib/travel/playback.svelte';
	import {
		axisTicks,
		entryIndexAt,
		stepEntryIndex,
		type AxisTick,
		type TimelineEntry,
		type TimelineFocus
	} from '$lib/travel/timeline';
	import { legLabel } from './leg-labels';
	import { entryDetail } from './timeline-labels';

	interface Props {
		/** The legs of the chosen trajectory, in flight order. */
		entries: readonly TimelineEntry[];
		/** The same trajectory as geometry, for placing the camera on the arc
		 *  itself. Null when the route has none that could be rebuilt. */
		path: TrajectoryPath | null;
		clock: SimClock;
		/** Look at where an entry happens, without leaving the trip — the planner
		 *  owns the URL, so this moves the camera and nothing else. */
		onFocus: (target: TimelineFocus) => void;
	}
	let { entries, path, clock, onFocus }: Props = $props();

	/** A spot on the drawn arc for `entry`, or the body it happens at when the
	 *  route has no drawable geometry. */
	function focusEntry(entry: TimelineEntry): void {
		const viewpoint = path ? pathViewpoint(path, entry.startJd, entry.endJd) : null;
		if (viewpoint && path) {
			onFocus({ kind: 'point', centerId: viewpoint.centerId ?? path.centerId, r: viewpoint.r });
		} else if (entry.bodyId) {
			onFocus({ kind: 'body', bodyId: entry.bodyId });
		}
	}

	// Read through rather than captured: the route can be re-picked, and the props
	// re-bound, while the timeline is up.
	const player = new TripPlayback({
		get clock() {
			return clock;
		},
		entries: () => entries,
		focus: (entry) => focusEntry(entry)
	});
	$effect(() => () => player.dispose());

	let startJd = $derived(entries[0]?.startJd ?? 0);
	let endJd = $derived(entries[entries.length - 1]?.endJd ?? 0);
	let spanDays = $derived(endJd - startJd);
	let activeIndex = $derived(entryIndexAt(entries, clock.jd));
	let ticks = $derived(spanDays > 0 ? axisTicks(startJd, endJd, 7) : []);

	/** Where `jd` sits along the track, clamped: the clock is free to be years off
	 *  either end of the trip, and the handle should sit at the end it ran past. */
	function fraction(jd: number): number {
		if (!(spanDays > 0)) return 0;
		return Math.min(1, Math.max(0, (jd - startJd) / spanDays));
	}

	let clockFraction = $derived(fraction(clock.jd));

	/** Land on `entries[index]` exactly as a click on the track there would:
	 *  clock on its date, camera on the craft. The entry's own place on the
	 *  line stands in for a date the craft isn't drawn at. */
	function pick(index: number): void {
		player.stop();
		const entry = entries[index];
		if (!entry) return;
		if (!seekToJd(entry.startJd)) focusEntry(entry);
	}

	/** Land on the entry with this id — how a step dot on the map presses the
	 *  card it stands for, playback stop included. */
	export function pickId(id: string): void {
		const index = entries.findIndex((entry) => entry.id === id);
		if (index >= 0) pick(index);
	}

	let trackEl: HTMLButtonElement | undefined = $state();

	/** Move the clock, and take the camera along with the craft it moves. True
	 *  when the craft was there to land on. */
	function seekToJd(jd: number): boolean {
		clock.setJD(jd);
		if (!path) return false;
		const craft = craftPositionAt(path, jd);
		if (!craft) return false;
		onFocus({
			kind: 'point',
			// The craft names its own frame: at an end drawn planet-frame it is
			// measured off that body, and the camera has to follow it there.
			centerId: craft.centerId,
			r: craft.r,
			track: true
		});
		return true;
	}

	function seekToFraction(f: number): void {
		seekToJd(startJd + spanDays * Math.min(1, Math.max(0, f)));
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
		player.stop();
		seekToFraction(fractionFromClientX(e.clientX));
		const move = (ev: PointerEvent) => seekToFraction(fractionFromClientX(ev.clientX));
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
		if (e.key === 'ArrowRight' || e.key === 'ArrowUp') seekToFraction(clockFraction + nudge);
		else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') seekToFraction(clockFraction - nudge);
		else if (e.key === 'Home') seekToFraction(0);
		else if (e.key === 'End') seekToFraction(1);
		else return;
		player.stop();
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
		<h2 class="min-w-0 truncate text-sm font-medium">
			{entries[0]?.bodyName ?? ''}
			<MoveRightIcon class="inline size-[1em] align-[-0.125em] rtl:rotate-180" aria-hidden="true" />
			{entries[entries.length - 1]?.bodyName ?? ''}
			<span class="text-muted-foreground font-normal">· {m.travel_timeline()}</span>
		</h2>
		<div class="flex shrink-0 items-center gap-1">
			<span class="text-muted-foreground me-1 text-xs tabular-nums">
				{formatJulianDate(clock.jd)}
			</span>
			<button
				type="button"
				class="hover:bg-muted inline-flex size-7 items-center justify-center rounded-md transition-colors"
				onclick={() => pick(stepEntryIndex(entries, clock.jd, -1))}
				aria-label={m.travel_timeline_prev()}
				title={m.travel_timeline_prev()}
			>
				<ChevronLeftIcon class="size-4 rtl:rotate-180" />
			</button>
			<button
				type="button"
				class="hover:bg-muted inline-flex size-7 items-center justify-center rounded-md transition-colors"
				onclick={() => player.toggle()}
				aria-label={player.playing ? m.travel_timeline_stop() : m.travel_timeline_play()}
				title={player.playing ? m.travel_timeline_stop() : m.travel_timeline_play()}
			>
				{#if player.playing}
					<SquareIcon class="size-3.5 fill-current" />
				{:else}
					<PlayIcon class="size-4 rtl:rotate-180" />
				{/if}
			</button>
			<button
				type="button"
				class="hover:bg-muted inline-flex size-7 items-center justify-center rounded-md transition-colors"
				onclick={() => pick(stepEntryIndex(entries, clock.jd, 1))}
				aria-label={m.travel_timeline_next()}
				title={m.travel_timeline_next()}
			>
				<ChevronRightIcon class="size-4 rtl:rotate-180" />
			</button>
		</div>
	</div>

	<ol class="flex items-stretch gap-2">
		{#each entries as entry, index (entry.id)}
			{@const active = index === activeIndex}
			{@const color = PHASE_COLORS[entry.kind]}
			<li class="flex min-w-0 flex-1">
				<button
					type="button"
					onclick={() => pick(index)}
					aria-current={active ? 'true' : undefined}
					class="flex min-w-0 flex-1 flex-col items-start gap-0.5 rounded-lg border px-2.5 py-2 text-start transition-colors
						{active ? 'border-border bg-muted' : 'hover:bg-muted/50 border-transparent'}"
				>
					<span class="flex w-full min-w-0 items-center gap-1.5">
						<!-- A phase is a stretch of the bar below and wears its colour; a burn
						     is a point on it and has none of its own. -->
						{#if entry.isPhase && color}
							<span class="size-1.5 shrink-0 rounded-full" style="background: {color}"></span>
						{/if}
						<span class="min-w-0 truncate text-sm {active ? 'font-medium' : ''}">
							{legLabel(entry.kind)}
						</span>
					</span>
					<span class="text-muted-foreground w-full truncate text-xs tabular-nums">
						{formatJulianDate(entry.startJd)}
					</span>
					<span class="text-muted-foreground/70 w-full truncate text-[11px] tabular-nums">
						{entryDetail(entry)}
					</span>
				</button>
			</li>
		{/each}
	</ol>

	{#if spanDays > 0}
		<div class="relative h-9 px-1">
			<button
				type="button"
				bind:this={trackEl}
				role="slider"
				aria-label={m.travel_timeline_scrub()}
				aria-valuemin={0}
				aria-valuemax={Math.round(spanDays)}
				aria-valuenow={Math.round(clockFraction * spanDays)}
				aria-valuetext={formatJulianDate(clock.jd)}
				onpointerdown={startScrub}
				onkeydown={onTrackKey}
				class="focus-visible:ring-ring absolute inset-x-0 top-0 h-4 cursor-pointer rounded-full focus-visible:ring-2 focus-visible:outline-none"
			>
				<span class="bg-border absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full"></span>
				<!-- Phases: the stretches of the trip, each the colour its arc is drawn
				     in. Laid down twice, so the part already flown reads solid against
				     the part still ahead. -->
				{#each entries as entry (entry.id)}
					{#if entry.isPhase}
						{@const from = fraction(entry.startJd)}
						{@const to = fraction(entry.endJd)}
						{@const color = PHASE_COLORS[entry.kind] ?? 'currentColor'}
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
				<!-- Events: the burns, which happen at a point rather than over one. -->
				{#each entries as entry (entry.id)}
					{#if !entry.isPhase}
						<span
							class="bg-muted-foreground ring-background absolute top-1/2 size-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-1"
							style="inset-inline-start: {fraction(entry.startJd) * 100}%"
						></span>
					{/if}
				{/each}
				<span
					class="bg-foreground ring-background absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2"
					style="inset-inline-start: {clockFraction * 100}%"
				></span>
			</button>
			{#each ticks as tick (tick.jd)}
				<span
					class="text-muted-foreground/70 absolute top-4 -translate-x-1/2 text-[10px] whitespace-nowrap tabular-nums"
					style="inset-inline-start: {fraction(tick.jd) * 100}%"
				>
					{tickLabel(tick)}
				</span>
			{/each}
		</div>
	{/if}
</div>
