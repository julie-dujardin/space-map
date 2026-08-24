<script lang="ts" module>
	/** The value's type size. Content-driven, not decorative: a group counts
	 *  things — short figures with room to spare — while a body's cards carry a
	 *  quantity and a unit, and 6.42×10²³ kg does not fit a 92px card at lg. */
	export type StatSize = 'md' | 'lg';

	export interface Stat {
		label: string;
		value: string;
		/** What this particular number is: what it comes to against Earth, which
		 *  survey it belongs to, whether it is a bound. Anchored on the value,
		 *  never the label — the label means the same thing on every card. */
		tooltip?: string;
		/** Only where the colour carries meaning: state, hazard, outcome. */
		dot?: string;
		/** 0–1; draws the bar that gives the value its denominator. */
		share?: number;
		href?: string;
		onClick?: (e: MouseEvent) => void;
	}
</script>

<script lang="ts">
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';

	interface Props {
		stat: Stat;
		size?: StatSize;
	}

	let { stat, size = 'md' }: Props = $props();

	const VALUE: Record<StatSize, string> = {
		md: 'text-sm',
		lg: 'text-lg'
	};

	/** Under this the bar is a sliver that says less than the tooltip does. */
	const MIN_BAR_SHARE = 0.05;

	const CARD =
		'border-border/60 bg-muted/40 pointer-events-auto flex min-w-0 flex-col gap-1 rounded-md border p-2.5';
</script>

{#snippet value()}
	<!-- One line, always. A figure that wraps changes the row's height and every
	     card beside it, so the value truncates and gives its tail to the hint —
	     the card's own tooltip where it has one, the title otherwise. -->
	{@const title = stat.tooltip ? undefined : stat.value}
	{#if stat.href}
		<a
			href={stat.href}
			onclick={stat.onClick}
			{title}
			class="pointer-events-auto block truncate {VALUE[
				size
			]} font-semibold tabular-nums underline underline-offset-2">{stat.value}</a
		>
	{:else}
		<div {title} class="truncate {VALUE[size]} font-semibold tabular-nums">{stat.value}</div>
	{/if}
{/snippet}

{#snippet card(props: Record<string, unknown>)}
	<div class="{CARD} {stat.tooltip ? 'cursor-help' : ''}" {...props}>
		<div class="text-muted-foreground flex items-center gap-1.5 text-[10px] uppercase">
			{#if stat.dot}
				<span class="inline-block size-1.5 shrink-0 rounded-full {stat.dot}"></span>
			{/if}
			<span class="truncate">{stat.label}</span>
		</div>
		{@render value()}
		{#if stat.share != null && stat.share >= MIN_BAR_SHARE}
			<div class="bg-muted-foreground/30 h-0.5 w-full overflow-hidden rounded-full">
				<div
					class="h-full rounded-full {stat.dot ?? 'bg-muted-foreground'}"
					style="width: {Math.min(100, Math.max(0, stat.share * 100))}%"
				></div>
			</div>
		{/if}
	</div>
{/snippet}

<!-- The whole card is the trigger, not just the value: a card that says
     cursor-help everywhere but answers only over the figure reads as broken. -->
{#if stat.tooltip}
	<Tooltip.Root>
		<Tooltip.Trigger>
			{#snippet child({ props })}{@render card(props)}{/snippet}
		</Tooltip.Trigger>
		<Tooltip.Content>{stat.tooltip}</Tooltip.Content>
	</Tooltip.Root>
{:else}
	{@render card({})}
{/if}
