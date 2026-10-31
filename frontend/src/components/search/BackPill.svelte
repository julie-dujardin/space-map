<!-- The way back from a drilled-in page, named after the page. -->
<script lang="ts">
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';

	let { label, onclick }: { label: string; onclick: () => void } = $props();
</script>

<button
	type="button"
	class="inline-flex h-[26px] items-center gap-1 rounded-lg bg-accent px-2 text-sm font-medium text-foreground"
	{onclick}
>
	<ChevronLeftIcon class="size-4 rtl:rotate-180" />
	<span class="whitespace-nowrap">{label}</span>
</button>
