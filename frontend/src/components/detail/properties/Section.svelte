<script lang="ts">
	import { Separator } from '$lib/components/ui/separator/index.js';
	import type { Snippet } from 'svelte';

	interface Props {
		title: string;
		children: Snippet;
		header?: Snippet;
	}

	let { title, children, header }: Props = $props();
</script>

<!--
	Subgrid so the unit column lines up across every section in the same
	property grid. The outer wrapper inherits the parent's [auto_1fr_auto]
	tracks; the dl re-subgrids those tracks for its rows.
-->
<div class="col-span-3 grid grid-cols-subgrid gap-y-1">
	<h3 class="col-span-3 text-sm font-medium">{title}</h3>
	<div class="col-span-3"><Separator /></div>
	{#if header}<div class="col-span-3">{@render header()}</div>{/if}
	<dl class="col-span-3 grid grid-cols-subgrid gap-y-2.5 text-sm">
		{@render children()}
	</dl>
</div>
