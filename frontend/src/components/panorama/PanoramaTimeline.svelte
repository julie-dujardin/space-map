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
	}

	let { missionName, entries, clock, href, onPick, onClose, positionClass }: Props = $props();

	type Item = StripItem & { entry: PanoramaEntry };

	// What a card says is read off the entry when that card is drawn, not when
	// the strip opens: a traverse runs to thousands of stops, and formatting a
	// date for every one of them is most of the wait before the map expands.
	const items = $derived<Item[]>(
		entries.map((entry) => {
			const jd = entryJd(entry);
			let when: string | undefined;
			return {
				id: entry.id,
				entry,
				detail: entry.title,
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

	function step(delta: number): void {
		player.stop();
		const item = items[stepEntryIndex(items, clock.jd, delta)];
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
