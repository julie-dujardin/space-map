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
		/** Keeps the value on one line, such as a catalogue number. The label
		 *  wraps instead. */
		whole?: boolean;
		/** A word after the value on how it was had: assumed, estimated. */
		note?: string;
		/** The label is a name, kept as written: "exoplanet.eu". */
		labelIsName?: boolean;
		children?: Snippet;
	}

	let {
		label,
		tooltip,
		value,
		valueTooltip,
		whole = false,
		note,
		labelIsName = false,
		children
	}: Props = $props();

	let shownLabel = $derived(labelIsName ? label : ucfirst(label));
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
		{@render hinted(shownLabel, tooltip)}
	{:else}
		{shownLabel}
	{/if}
</dt>
<dd class="text-end [overflow-wrap:anywhere] {whole ? 'min-w-max' : 'min-w-0'}">
	{#if children}
		{@render children()}
	{:else if valueTooltip && value}
		{@render hinted(value, valueTooltip)}
	{:else}
		{value}
	{/if}
	{#if note}<span class="text-muted-foreground ms-1 text-xs whitespace-nowrap">{note}</span>{/if}
</dd>
