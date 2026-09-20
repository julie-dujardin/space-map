<!--
  Turns the orientation sensor on and off beside the other panorama chrome.
  Shown only where the sensor is within reach; the settings menu carries the
  standing preference and says why when it is not.
-->
<script lang="ts">
	import Rotate3dIcon from '@lucide/svelte/icons/rotate-3d';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		active: boolean;
		onToggle: () => void;
	}

	let { active, onToggle }: Props = $props();
</script>

<button
	type="button"
	onclick={onToggle}
	aria-pressed={active}
	title={m.panorama_gyro()}
	aria-label={m.panorama_gyro()}
	class="flex h-10 w-10 cursor-pointer items-center justify-center rounded-full
		backdrop-blur-md transition-colors md:h-8 md:w-8
		{active ? 'bg-white text-black hover:bg-white/85' : 'bg-black/40 text-white hover:bg-black/55'}"
>
	<Rotate3dIcon class="size-5 md:size-4" />
</button>
