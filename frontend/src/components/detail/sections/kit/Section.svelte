<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		children: Snippet;
		header?: Snippet;
		/** Full-width content after the rows — for anything that isn't a label/value pair. */
		footer?: Snippet;
	}

	let { title, children, header, footer }: Props = $props();
</script>

<div class="flex flex-col gap-1">
	<h3 class="text-sm font-medium">{title}</h3>
	<div class="border-border/60 border-t"></div>
	{#if header}{@render header()}{/if}
	<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2.5 text-sm">
		{@render children()}
	</dl>
	{#if footer}
		<div class="mt-2.5 flex flex-col gap-3">{@render footer()}</div>
	{/if}
</div>
