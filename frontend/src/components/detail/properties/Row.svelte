<script lang="ts">
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import { formatUnit, ucfirst, unitFullName, unitNeedsTooltip } from '$lib/format/quantities';
	import type { Snippet } from 'svelte';

	interface Props {
		label: string;
		tooltip?: string;
		value?: string;
		/** Unit code (e.g. "kilometre") rendered in the aligned unit column. */
		unit?: string | null;
		children?: Snippet;
	}

	let { label, tooltip, value, unit, children }: Props = $props();
</script>

<dt class="text-muted-foreground pr-4">
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
<dd class="min-w-0 text-end">
	{#if children}
		{@render children()}
	{:else}
		{value}
	{/if}
</dd>
<dd class="text-muted-foreground text-xs self-center" class:pl-1.5={unit}>
	{#if unit && unitNeedsTooltip(unit)}
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<span class="cursor-help decoration-dotted underline underline-offset-2" {...props}>
						{formatUnit(unit, true)}
					</span>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content>{unitFullName(unit)}</Tooltip.Content>
		</Tooltip.Root>
	{:else if unit}
		{formatUnit(unit, true)}
	{/if}
</dd>
