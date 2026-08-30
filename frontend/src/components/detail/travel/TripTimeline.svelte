<!--
  The trip along the bottom of the map: every leg of the chosen trajectory, in
  order, against the clock the scene is drawn at. Picking one moves the
  simulation and camera to it, but never the *departure* — when the trip
  leaves is the planner's term, not this widget's.

  The strip itself is `TimelineStrip`, which knows nothing of trips; what a
  pick means — the clock, and the camera on the craft in its own frame — is
  what lives here.
-->
<script lang="ts">
	import MoveRightIcon from '@lucide/svelte/icons/move-right';
	import * as m from '$lib/paraglide/messages.js';
	import TimelineStrip from '../../timeline/TimelineStrip.svelte';
	import { formatJulianDate } from '$lib/format/date';
	import { pathViewpoint, type TrajectoryPath } from '$lib/math/travel/path';
	import { craftPositionAt } from '$lib/math/travel/path-sample';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { stepEntryIndex } from '$lib/timeline/axis';
	import type { StripItem } from '$lib/timeline/strip';
	import { PHASE_COLORS } from '$lib/travel/arc-colors';
	import { TripPlayback } from '$lib/travel/playback.svelte';
	import type { TimelineEntry, TimelineFocus } from '$lib/travel/timeline';
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

	let items = $derived(
		entries.map(
			(entry): StripItem => ({
				id: entry.id,
				label: legLabel(entry.kind),
				when: formatJulianDate(entry.startJd),
				detail: entryDetail(entry),
				startJd: entry.startJd,
				endJd: entry.endJd,
				isPhase: entry.isPhase,
				color: PHASE_COLORS[entry.kind]
			})
		)
	);

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
</script>

{#snippet title()}
	{entries[0]?.bodyName ?? ''}
	<MoveRightIcon class="inline size-[1em] align-[-0.125em] rtl:rotate-180" aria-hidden="true" />
	{entries[entries.length - 1]?.bodyName ?? ''}
	<span class="text-muted-foreground font-normal">· {m.travel_timeline()}</span>
{/snippet}

<TimelineStrip
	{items}
	{title}
	{clock}
	onPick={pick}
	onScrub={(jd) => {
		player.stop();
		seekToJd(jd);
	}}
	playing={player.playing}
	playLabel={m.travel_timeline_play()}
	onTogglePlay={() => player.toggle()}
	onStep={(delta) => pick(stepEntryIndex(entries, clock.jd, delta))}
/>
