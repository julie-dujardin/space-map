<!--
  A spacecraft's record along the bottom of the map, in the same strip the
  trajectory planner uses: what it did, in order, against the clock the scene
  is drawn at.

  Picking a moment moves time and nothing else. The craft is already the
  focused body, so the camera stays with it — and where the record runs past
  the ephemeris, the date is still the date, marked as one the map has no
  craft to draw at.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import TimelineStrip from '../../timeline/TimelineStrip.svelte';
	import { fetchObjectDetail, type ProbeEvents } from '$lib/fetch/objects/object-data';
	import type { ProbeCoverage } from '$lib/fetch/metadata';
	import { coverageGaps, eventStripItems } from '$lib/probes/event-timeline';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { stepEntryIndex } from '$lib/timeline/axis';
	import { TripPlayback } from '$lib/travel/playback.svelte';

	interface Props {
		/** The focused probe's object id. */
		objectId: string;
		/** What to call it — the drawer's own display name, so the strip and the
		 *  panel behind it agree. */
		name: string;
		clock: SimClock;
	}

	let { objectId, name, clock }: Props = $props();

	let events = $state.raw<ProbeEvents | null>(null);
	let coverage = $state.raw<ProbeCoverage | undefined>(undefined);

	// The drawer has usually fetched this bundle already; the cache makes the
	// second read free, and asking for it here keeps the strip standalone.
	$effect(() => {
		const id = objectId;
		let cancelled = false;
		fetchObjectDetail(id, false).then((detail) => {
			if (cancelled) return;
			events = detail.global?.events ?? null;
			coverage = detail.global?.coverage;
		});
		return () => {
			cancelled = true;
			events = null;
		};
	});

	let items = $derived(events ? eventStripItems(events.items, coverage) : []);
	let gaps = $derived(
		items.length ? coverageGaps(coverage, items[0].startJd, items[items.length - 1].endJd) : []
	);

	const player = new TripPlayback({
		get clock() {
			return clock;
		},
		entries: () => items,
		// The craft is the focus already; a moment of its own record is a date,
		// not a place to be taken to.
		focus: () => {}
	});
	$effect(() => () => player.dispose());

	function pick(index: number): void {
		player.stop();
		const item = items[index];
		if (item) clock.jumpTo(item.startJd);
	}
</script>

{#if items.length > 1}
	{#snippet title()}
		{name}
		<span class="text-muted-foreground font-normal">· {m.probe_timeline()}</span>
	{/snippet}

	<TimelineStrip
		{items}
		{gaps}
		{title}
		{clock}
		onPick={pick}
		onScrub={(jd) => {
			player.stop();
			clock.setJD(jd);
		}}
		playing={player.playing}
		onTogglePlay={() => player.toggle()}
		playLabel={m.probe_timeline_play()}
		onStep={(delta) => pick(stepEntryIndex(items, clock.jd, delta))}
	/>
{/if}
