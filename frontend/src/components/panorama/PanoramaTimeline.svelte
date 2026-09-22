<!--
  The traverse as a strip of cards with a picture each, along the bottom of the
  viewer. Picking a card opens that panorama; playing walks the traverse.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import TimelineStrip from '../timeline/TimelineStrip.svelte';
	import type { PanoramaEntry } from '$lib/fetch/objects/object-data';
	import { versionedUrl } from '$lib/fetch/data-base';
	import { formatIsoDate } from '$lib/format/date';
	import { entryJd } from '$lib/panorama/minimap';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { stepEntryIndex } from '$lib/timeline/axis';
	import type { StripItem } from '$lib/timeline/strip';
	import { TripPlayback } from '$lib/travel/playback.svelte';

	interface Props {
		missionName: string;
		entries: readonly PanoramaEntry[];
		clock: SimClock;
		/** The card of each panorama is a link there. */
		href: (entry: PanoramaEntry) => string;
		/** Opens a panorama the reader did not click: a step or playback. */
		onPick: (entry: PanoramaEntry) => void;
		onClose: () => void;
		positionClass: string;
		/** The panorama on screen. Stops taken at the same moment by two cameras
		 *  share a timestamp, so the clock cannot name it. */
		activeId?: string;
	}

	let { missionName, entries, clock, href, onPick, onClose, positionClass, activeId }: Props =
		$props();

	type Item = StripItem & { entry: PanoramaEntry };

	// What a card says is read off the entry when that card is drawn, not when
	// the strip opens: a traverse runs to thousands of stops, and formatting a
	// date for every one of them is most of the wait before the map expands.
	//
	// No `detail`: only some stops are titled, and the row is as tall as its
	// tallest card, so a title line would resize the strip — and the minimap
	// sized from it — as the reader scrolls through the traverse.
	const items = $derived<Item[]>(
		entries.map((entry) => {
			const jd = entryJd(entry);
			let when: string | undefined;
			return {
				id: entry.id,
				entry,
				isPhase: false,
				startJd: jd,
				endJd: jd,
				get label() {
					return entry.sol !== undefined ? m.panorama_sol({ sol: entry.sol }) : entry.id;
				},
				get when() {
					return (when ??= formatIsoDate(entry.time));
				},
				get image() {
					return versionedUrl(`/v1/panoramas/${entry.id}-preview.webp`, 'panoramas');
				},
				get href() {
					return href(entry);
				}
			};
		})
	);

	const player = new TripPlayback<Item>({
		get clock() {
			return clock;
		},
		entries: () => items,
		focus: (item) => onPick(item.entry)
	});
	$effect(() => () => player.dispose());

	// Stepping walks from the stop on screen, not from the clock: two cameras
	// shooting at once share a timestamp, and a step off the clock would land
	// back on the first of them.
	function step(delta: number): void {
		player.stop();
		const at = activeId === undefined ? -1 : items.findIndex((item) => item.id === activeId);
		const index =
			at >= 0
				? Math.min(items.length - 1, Math.max(0, at + delta))
				: stepEntryIndex(items, clock.jd, delta);
		const item = items[index];
		if (item) onPick(item.entry);
	}
</script>

{#snippet title()}
	{missionName}
	<span class="text-muted-foreground font-normal">· {m.panorama_traverse()}</span>
{/snippet}

<TimelineStrip
	{items}
	{title}
	{clock}
	{positionClass}
	{onClose}
	{activeId}
	closeLabel={m.panorama_map_collapse()}
	onPick={() => player.stop()}
	onScrub={(jd) => {
		player.stop();
		clock.setJD(jd);
	}}
	playing={player.playing}
	onTogglePlay={() => player.toggle()}
	playLabel={m.panorama_traverse_play()}
	onStep={step}
/>
