<script lang="ts">
	import { getContext } from 'svelte';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import { formatNumber } from '$lib/format/quantities';
	import ChartPager from './ChartPager.svelte';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusClick, focusHref, groupClick, groupHref } from '$lib/state/focus-link';
	import type { DrawerTab } from '$lib/state/view';

	/** One tally per row — moons per planet, features per body, names per origin.
	 *  Rows with no `primary_id` (naming origins) have nowhere to go, so they
	 *  render unlinked; a `group` row opens a collection page instead of
	 *  focusing a body (the libration points probes are sent to). */
	export interface CountPerBodyEntry {
		name: string;
		primary_type?: 'object' | 'group';
		primary_id?: string;
		n: number;
		/** The member's own exported tint, for the bodies `BODY_COLORS` has no
		 *  hand-picked entry for — most moons. */
		color?: string;
	}

	interface Props {
		entries: CountPerBodyEntry[];
		title: string;
		/** Tab the row opens on the host body. */
		tab?: Exclude<DrawerTab, 'overview'>;
		/** Body id → localized label, when the bundle ships one. */
		names?: Record<string, string>;
		/** Narrows the target tab's list to one feature type, so a row on an
		 *  `ft-` page lands on that body's features of that type — not all of them. */
		featureType?: string;
		/** Small-caps note beside the title, e.g. that the bars are logarithmic. */
		hint?: string;
		/** Bar length as a 0–1 fraction, for values a share of the largest would
		 *  misdraw — ring masses span fourteen decades and go on a log axis. */
		fraction?: (entry: CountPerBodyEntry) => number;
		/** Row figure, where `n` is not what the row should read as. */
		text?: (entry: CountPerBodyEntry) => string;
		/** Hangs off the figure, not the name: a comparison is about the number.
		 *  Undefined for the rows it says nothing about — Earth against itself. */
		tooltip?: (entry: CountPerBodyEntry) => string | undefined;
	}
	let { entries, title, tab, names, featureType, hint, fraction, text, tooltip }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	/** Rows per page. Craters span ~50 bodies and the naming origins run to 60,
	 *  so both page; a planet's moons fit in one. */
	const PAGE_SIZE = 12;

	// Bars scale against the whole set, not the page, so pages stay comparable.
	let maxCount = $derived(entries.length > 0 ? Math.max(...entries.map((e) => e.n)) : 0);
	let pageCount = $derived(Math.max(1, Math.ceil(entries.length / PAGE_SIZE)));
	let page = $state(0);
	// A shorter list (another group focused) would otherwise strand the page.
	$effect(() => {
		if (page > pageCount - 1) page = pageCount - 1;
	});
	let visible = $derived(entries.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE));

	function label(e: CountPerBodyEntry): string {
		return (e.primary_id ? names?.[e.primary_id] : undefined) ?? e.name;
	}

	function href(e: CountPerBodyEntry, id: string): string | undefined {
		return e.primary_type === 'group'
			? groupHref(appState, id, label(e))
			: focusHref(appState, id, label(e), tab, featureType);
	}

	function onclick(e: CountPerBodyEntry, id: string): (ev: MouseEvent) => void {
		return e.primary_type === 'group'
			? groupClick(appState, id, label(e))
			: focusClick(focusObject, id, label(e), { tab, featureType });
	}

	/** Same order MoonDiscRow uses: the hand-picked UI tint, then whatever the
	 *  bundle derived for the body, then grey. */
	function color(e: CountPerBodyEntry): string {
		return (e.primary_id ? BODY_COLORS[e.primary_id] : undefined) ?? e.color ?? DEFAULT_BODY_COLOR;
	}

	// Rows are subgrids of one grid, so columns are sized across the whole
	// list, not per row — a per-row `auto` let the Sun's 0.125 bar draw
	// shorter than Jupiter's 0.1 bar, just because "0.125" is the wider string.
	// `fit-content`, not `minmax(0, …)`, on the name: the latter behaves as a
	// fixed width since the `1fr` beside it grabs the free space, leaving a gap
	// in front of short names' bars. The cap is where names start truncating.
	let columns = $derived(text ? 'fit-content(6rem) 1fr auto' : 'fit-content(9rem) 1fr 2.5rem');
</script>

{#snippet row(e: CountPerBodyEntry)}
	{@const tip = tooltip?.(e)}
	{@const figure = text ? text(e) : formatNumber(e.n)}
	<div class="text-muted-foreground truncate text-sm" title={label(e)}>{label(e)}</div>
	<div class="bg-muted/60 relative h-[16px] rounded-sm">
		<div
			class="absolute top-1/2 start-0 h-[10px] -translate-y-1/2 rounded-sm"
			style:width="{100 * (fraction ? fraction(e) : maxCount > 0 ? e.n / maxCount : 0)}%"
			style:background-color={color(e)}
		></div>
	</div>
	{#if tip}
		<Tooltip.Root>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<div
						{...props}
						class="text-muted-foreground cursor-help text-end text-sm whitespace-nowrap tabular-nums"
					>
						{figure}
					</div>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content>{tip}</Tooltip.Content>
		</Tooltip.Root>
	{:else}
		<div class="text-muted-foreground text-end text-sm whitespace-nowrap tabular-nums">
			{figure}
		</div>
	{/if}
{/snippet}

{#if entries.length > 0}
	<div class="flex flex-col gap-1">
		<div class="flex items-baseline justify-between gap-2">
			<h3 class="text-sm font-medium">{title}</h3>
			<div class="flex items-baseline gap-2">
				{#if hint}
					<span class="text-muted-foreground text-[10px] uppercase">{hint}</span>
				{/if}
				<ChartPager {page} {pageCount} onpage={(p) => (page = p)} />
			</div>
		</div>
		<div class="border-border/60 border-t"></div>
		<!-- One grid for the list, each row a subgrid of it, so the columns line
		     up across rows and the figure column is sized by the whole set. -->
		<div class="mt-1 grid gap-x-2 gap-y-[3px]" style="grid-template-columns: {columns}">
			{#each visible as e (e.primary_id ?? e.name)}
				{#if appState && e.primary_id}
					<a
						href={href(e, e.primary_id)}
						onclick={onclick(e, e.primary_id)}
						class="hover:bg-muted/40 col-span-3 grid grid-cols-subgrid items-center rounded-sm px-1 py-px"
					>
						{@render row(e)}
					</a>
				{:else}
					<div class="col-span-3 grid grid-cols-subgrid items-center rounded-sm px-1 py-px">
						{@render row(e)}
					</div>
				{/if}
			{/each}
		</div>
	</div>
{/if}
