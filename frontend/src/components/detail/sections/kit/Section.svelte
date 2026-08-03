<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		/** Optional: a section can be all chart and no label/value pairs. */
		children?: Snippet;
		header?: Snippet;
		/** Full-width content after the rows — for anything that isn't a label/value pair. */
		footer?: Snippet;
		/** A qualifier on the whole section, set opposite the title. The
		 *  cross-sections use it to say what they are drawn to scale against. */
		meta?: string;
	}

	let { title, children, header, footer, meta }: Props = $props();
</script>

<div class="flex flex-col gap-1">
	<div class="flex items-baseline justify-between gap-3">
		<h3 class="text-sm font-medium">{title}</h3>
		{#if meta}
			<span class="text-muted-foreground shrink-0 text-[10px] tabular-nums">{meta}</span>
		{/if}
	</div>
	<div class="border-border/60 border-t"></div>
	{#if header}{@render header()}{/if}
	{#if children}
		<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2.5 text-sm">
			{@render children()}
		</dl>
	{/if}
	{#if footer}
		<div class="mt-2.5 flex flex-col gap-3">{@render footer()}</div>
	{/if}
</div>
