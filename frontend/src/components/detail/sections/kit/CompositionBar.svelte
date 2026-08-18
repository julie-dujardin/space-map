<script lang="ts">
	/**
	 * A stacked share bar with a legend, both hoverable — the one composition
	 * chart in the panel. The atmosphere's gases, the body's materials and a
	 * layer's chemistry all arrive as entries and are drawn identically: same
	 * ranking, same trace bucket, same hover sentence. A reader who has learned
	 * what the grey block means on the Overview should not have to relearn it on
	 * a layer card.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import { foldTrace, MIN_TRACE, type CompositionEntry } from '$lib/charts/composition-bar';
	import { formatPercent, percentParts, spanFields } from '$lib/format/quantities';

	interface Props {
		entries: CompositionEntry[];
		/** What the shares are shares of, where that needs saying. */
		caption?: string | null;
	}

	let { entries, caption = null }: Props = $props();

	const TRACE_KEY = '__trace__';

	let composition = $derived(foldTrace(entries));

	let segments: CompositionEntry[] = $derived.by(() => {
		const { shown, trace } = composition;
		if (trace < MIN_TRACE) return shown;
		return [
			...shown,
			{
				key: TRACE_KEY,
				label: m.composition_trace(),
				name: m.composition_trace_full(),
				share: trace,
				color: 'var(--gas-trace)'
			}
		];
	});

	function value(segment: CompositionEntry): string {
		return `${segment.limit ? '<' : ''}${formatPercent(segment.share)}`;
	}

	function tooltip(segment: CompositionEntry): string {
		const name = segment.name;
		return segment.limit
			? m.composition_limit({ name, value: formatPercent(segment.share) })
			: m.composition_value({ name, value: formatPercent(segment.share) });
	}

	// Upper limits are drawn hatched over their hue and read "under" in every
	// label, so a bound never passes for a measurement at a glance.
	const HATCH =
		'background-image: repeating-linear-gradient(135deg, transparent 0 3px, rgba(0,0,0,0.35) 3px 5px)';
</script>

<!-- Everything the number on its own does not say: the width a source published
     around it, and what the trace bucket stands for so it is not a dead end. -->
{#snippet detail(segment: CompositionEntry)}
	{#if segment.range}
		<span class="opacity-70">
			{m.structure_share_range(
				spanFields(percentParts(segment.range[0]), percentParts(segment.range[1]))
			)}
		</span>
	{/if}
	{#if segment.key === TRACE_KEY}
		<dl class="mt-1 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 leading-snug opacity-70">
			{#each composition.folded as member (member.key)}
				<dt>{member.name}</dt>
				<!-- One significant digit: trace members run down to parts per billion,
				     where a fixed digit count rounds everything to zero. -->
				<dd class="text-end tabular-nums">{formatPercent(member.share, 1)}</dd>
			{/each}
		</dl>
	{/if}
{/snippet}

{#snippet swatch(segment: CompositionEntry)}
	<span class="size-2 shrink-0 rounded-full" style="background: {segment.color}" aria-hidden="true"
	></span>
	<span>{segment.label}</span>
	<span class="text-muted-foreground tabular-nums">{value(segment)}</span>
{/snippet}

{#if segments.length}
	<div class="mt-2 mb-1.5 flex flex-col gap-2">
		<div class="flex h-2.5 w-full gap-0.5" role="img" aria-label={segments.map(tooltip).join(', ')}>
			{#each segments as segment (segment.key)}
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
						{tooltip(segment)}
						{@render detail(segment)}
					</Tooltip.Content>
				</Tooltip.Root>
			{/each}
		</div>

		<ul class="flex flex-wrap gap-x-3 gap-y-1 text-xs">
			{#each segments as segment (segment.key)}
				<li>
					<!-- The legend hovers only where its label abbreviates the thing —
					     a formula, a symbol, "trace". "rock" spells itself out. -->
					{#if segment.label === segment.name}
						<span class="flex items-center gap-1.5">{@render swatch(segment)}</span>
					{:else}
						<Tooltip.Root>
							<Tooltip.Trigger>
								{#snippet child({ props })}
									<span class="flex cursor-help items-center gap-1.5" {...props}>
										{@render swatch(segment)}
									</span>
								{/snippet}
							</Tooltip.Trigger>
							<Tooltip.Content class="flex-col items-start gap-0">
								{tooltip(segment)}
								{@render detail(segment)}
							</Tooltip.Content>
						</Tooltip.Root>
					{/if}
				</li>
			{/each}
		</ul>

		{#if caption}
			<p class="text-muted-foreground text-[11px] leading-snug">{caption}</p>
		{/if}
	</div>
{/if}
