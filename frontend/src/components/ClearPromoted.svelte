<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import MapPinXIcon from '@lucide/svelte/icons/map-pin-x';

	interface Props {
		onClear: () => void;
	}

	let { onClear }: Props = $props();
</script>

<button
	onclick={onClear}
	class="pointer-events-auto flex items-center justify-center
		w-12 h-12 md:w-10 md:h-10 rounded-full
		bg-primary-foreground hover:bg-primary-foreground/80
		text-primary transition-colors cursor-pointer"
	title={m.clear_promoted()}
	aria-label={m.clear_promoted()}
>
	<MapPinXIcon class="size-7 md:size-5" />
</button>
