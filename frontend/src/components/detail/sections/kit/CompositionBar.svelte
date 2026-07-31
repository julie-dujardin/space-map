<script lang="ts">
	/**
	 * A stacked share bar with a legend, both hoverable. Shared by the
	 * atmosphere and interior panels so a body that has both — every gas giant
	 * — draws them identically.
	 */
	import type { Snippet } from 'svelte';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { CompositionSegment } from '$lib/charts/composition-bar';

	interface Props {
		segments: CompositionSegment[];
		/** Extra hover content for a segment that stands for several things —
		 *  the atmosphere's trace bucket lists its members. */
		detail?: Snippet<[CompositionSegment]>;
		/** What the shares are shares of, where that needs saying. */
		caption?: string | null;
	}

	let { segments, detail, caption = null }: Props = $props();

	// Upper limits are drawn hatched over their hue and read "under" in every
	// label, so a bound never passes for a measurement at a glance.
	const HATCH =
		'background-image: repeating-linear-gradient(135deg, transparent 0 3px, rgba(0,0,0,0.35) 3px 5px)';
</script>

{#snippet swatch(segment: CompositionSegment)}
	<span class="size-2 shrink-0 rounded-full" style="background: {segment.color}" aria-hidden="true"
	></span>
	<span>{segment.label}</span>
	<span class="text-muted-foreground tabular-nums">{segment.value}</span>
{/snippet}

{#if segments.length}
	<div class="mt-2 mb-1.5 flex flex-col gap-2">
		<div
			class="flex h-2.5 w-full gap-0.5"
			role="img"
			aria-label={segments.map((s) => s.tooltip).join(', ')}
		>
			{#each segments as segment (segment.key)}
				{#if segment.tooltip}
					<Tooltip.Root>
						<Tooltip.Trigger>
							{#snippet child({ props })}
								<span
									class="h-full cursor-help rounded-[2px] first:rounded-s-full last:rounded-e-full"
									style="flex: {segment.share}; background: {segment.color}; {segment.limit
										? HATCH
										: ''}"
									{...props}
								></span>
							{/snippet}
						</Tooltip.Trigger>
						<Tooltip.Content class="flex-col items-start gap-0">
							{segment.tooltip}
							{@render detail?.(segment)}
						</Tooltip.Content>
					</Tooltip.Root>
				{:else}
					<span
						class="h-full rounded-[2px] first:rounded-s-full last:rounded-e-full"
						style="flex: {segment.share}; background: {segment.color}; {segment.limit ? HATCH : ''}"
					></span>
				{/if}
			{/each}
		</div>

		<ul class="flex flex-wrap gap-x-3 gap-y-1 text-xs">
			{#each segments as segment (segment.key)}
				<li>
					{#if segment.labelIsAbbreviated}
						<Tooltip.Root>
							<Tooltip.Trigger>
								{#snippet child({ props })}
									<span class="flex cursor-help items-center gap-1.5" {...props}>
										{@render swatch(segment)}
									</span>
								{/snippet}
							</Tooltip.Trigger>
							<Tooltip.Content class="flex-col items-start gap-0">
								{segment.tooltip}
								{@render detail?.(segment)}
							</Tooltip.Content>
						</Tooltip.Root>
					{:else}
						<span class="flex items-center gap-1.5">{@render swatch(segment)}</span>
					{/if}
				</li>
			{/each}
		</ul>

		{#if caption}
			<p class="text-muted-foreground text-[11px] leading-snug">{caption}</p>
		{/if}
	</div>
{/if}
