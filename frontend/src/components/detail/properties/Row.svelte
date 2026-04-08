<script lang="ts">
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import { ucfirst } from '$lib/format/quantities';
	import type { Snippet } from 'svelte';

	interface Props {
		label: string;
		tooltip?: string;
		value?: string;
		children?: Snippet;
	}

	let { label, tooltip, value, children }: Props = $props();
</script>

<dt class="text-muted-foreground">
	{#if tooltip}
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<span class="cursor-help decoration-dotted underline underline-offset-2" {...props}>
						{ucfirst(label)}
					</span>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content>{tooltip}</Tooltip.Content>
		</Tooltip.Root>
	{:else}
		{ucfirst(label)}
	{/if}
</dt>
<dd class="text-right">
	{#if children}
		{@render children()}
	{:else}
		{value}
	{/if}
</dd>
