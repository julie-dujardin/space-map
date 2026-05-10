<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import MapPinXIcon from '@lucide/svelte/icons/map-pin-x';
	import { toast } from 'svelte-sonner';

	interface Props {
		count: number;
		onClear: () => void;
	}

	let { count, onClear }: Props = $props();

	function handleClick() {
		const cleared = count;
		onClear();
		toast.success(m.cleared_n_promoted({ count: cleared }));
	}
</script>

<button
	onclick={handleClick}
	class="pointer-events-auto relative flex items-center justify-center
		w-10 h-10 md:w-8 md:h-8 rounded-full
		bg-black/40 backdrop-blur-md hover:bg-black/55
		text-white transition-colors cursor-pointer"
	title={m.clear_promoted()}
	aria-label={m.clear_promoted()}
>
	<MapPinXIcon class="size-5 md:size-4" />
	<span
		class="absolute -top-1 -end-1 min-w-4 h-4 px-1 rounded-full
			bg-white text-black text-[10px] leading-none font-medium
			flex items-center justify-center pointer-events-none"
		aria-hidden="true"
	>
		{count}
	</span>
</button>
