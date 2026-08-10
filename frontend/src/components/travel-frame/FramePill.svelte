<!--
  Which frame the map draws the trip's ends in: a labelled segmented pill over
  the map, both ends always showing.

  Map chrome rather than a panel setting, because it changes the picture and not
  the trip. On its face rather than behind a menu, because it is not a setting
  you set once — it is which of two pictures you are looking at, and one click is
  the whole of it.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { TrajectoryFrame } from '$lib/math/travel';
	import { frameOptions } from './frame-options';

	interface Props {
		frame: TrajectoryFrame;
		onSelect: (frame: TrajectoryFrame) => void;
	}
	let { frame, onSelect }: Props = $props();

	const options = $derived(frameOptions());
</script>

<!-- The label leads the segments inside the same pill, behind a hairline. It is
     dropped below md, where the phrase is wider than the control it names and
     the two options carry themselves. -->
<div class="pointer-events-auto inline-flex items-center rounded-full bg-black/40 backdrop-blur-md">
	<span class="hidden truncate ps-3.5 pe-3 text-xs text-white/60 md:inline" aria-hidden="true">
		{m.travel_frame()}
	</span>
	<span class="hidden h-4 w-px bg-white/15 md:inline-block"></span>
	<!-- Named by the group rather than by the visible label, so a screen reader
	     hears it once. No glass of its own: it is already on the pill's. -->
	<div
		class="inline-flex items-center gap-0.5 rounded-full p-0.5"
		role="group"
		aria-label={m.travel_frame()}
	>
		{#each options as option (option.value)}
			{@const active = option.value === frame}
			<button
				type="button"
				aria-pressed={active}
				title={option.description}
				onclick={() => onSelect(option.value)}
				class="flex cursor-pointer items-center gap-1.5 rounded-full px-3 py-1.5 text-xs transition-colors
					{active ? 'bg-white font-medium text-black' : 'text-white/70 hover:text-white'}"
			>
				<option.Icon class="size-3.5" />
				{option.label}
			</button>
		{/each}
	</div>
</div>
