<script lang="ts">
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import { ucfirst } from '$lib/format/quantities';
	import type { Snippet } from 'svelte';

	interface Props {
		label: string;
		/** What the label means — a definition of the quantity, the same for
		 *  every body that has this row. */
		tooltip?: string;
		value?: string;
		/** What this particular number is: its published width, the survey it
		 *  belongs to, what it comes to against Earth. Hangs off the value
		 *  because it changes with the value. */
		valueTooltip?: string;
		children?: Snippet;
	}

	let { label, tooltip, value, valueTooltip, children }: Props = $props();
</script>

{#snippet hinted(text: string, hint: string)}
	<Tooltip.Root>
		<Tooltip.Trigger>
			{#snippet child({ props })}
				<span class="cursor-help decoration-dotted underline underline-offset-2" {...props}>
					{text}
				</span>
			{/snippet}
		</Tooltip.Trigger>
		<Tooltip.Content>{hint}</Tooltip.Content>
	</Tooltip.Root>
{/snippet}

<dt class="text-muted-foreground">
	{#if tooltip}
		{@render hinted(ucfirst(label), tooltip)}
	{:else}
		{ucfirst(label)}
	{/if}
</dt>
<dd class="min-w-0 text-end">
	{#if children}
		{@render children()}
	{:else if valueTooltip && value}
		{@render hinted(value, valueTooltip)}
	{:else}
		{value}
	{/if}
</dd>
