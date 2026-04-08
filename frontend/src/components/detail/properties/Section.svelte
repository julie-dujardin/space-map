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

<div class="flex flex-col gap-1">
	<h3 class="text-sm font-medium">{title}</h3>
	<Separator />
	{#if header}{@render header()}{/if}
	<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
		{@render children()}
	</dl>
</div>
