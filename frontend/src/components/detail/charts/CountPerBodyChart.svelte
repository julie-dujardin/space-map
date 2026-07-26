<script lang="ts">
	import { getContext } from 'svelte';
	import { formatNumber } from '$lib/format/quantities';
	import ChartPager from './ChartPager.svelte';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusClick, focusHref } from '$lib/state/focus-link';
	import type { DrawerTab } from '$lib/state/view';

	/** One tally per row — moons per planet, features per body, names per origin.
	 *  Rows with no `primary_id` (naming origins) have nowhere to go, so they
	 *  render unlinked. */
	export interface CountPerBodyEntry {
		name: string;
		primary_type?: 'object';
		primary_id?: string;
		n: number;
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
	}
	let { entries, title, tab, names, featureType }: Props = $props();

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

	function color(id: string | undefined): string {
		return (id ? BODY_COLORS[id] : undefined) ?? DEFAULT_BODY_COLOR;
	}
</script>

{#snippet row(e: CountPerBodyEntry)}
	<div class="text-muted-foreground truncate text-sm" title={label(e)}>{label(e)}</div>
	<div class="bg-muted/30 relative h-[16px] rounded-sm">
		<div
			class="absolute top-1/2 start-0 h-[10px] -translate-y-1/2 rounded-sm"
			style:width="{maxCount > 0 ? (e.n / maxCount) * 100 : 0}%"
			style:background-color={color(e.primary_id)}
		></div>
	</div>
	<div class="text-muted-foreground text-end text-sm tabular-nums">{formatNumber(e.n)}</div>
{/snippet}

{#if entries.length > 0}
	<div class="flex flex-col gap-1">
		<div class="flex items-baseline justify-between gap-2">
			<h3 class="text-sm font-medium">{title}</h3>
			<ChartPager {page} {pageCount} onpage={(p) => (page = p)} />
		</div>
		<div class="border-border/60 border-t"></div>
		<div class="mt-1 flex flex-col gap-[3px]">
			{#each visible as e (e.primary_id ?? e.name)}
				{#if appState && e.primary_id}
					<a
						href={focusHref(appState, e.primary_id, label(e), tab, featureType)}
						onclick={focusClick(focusObject, e.primary_id, label(e), { tab, featureType })}
						class="hover:bg-muted/40 grid items-center gap-2 rounded-sm px-1 py-px"
						style="grid-template-columns: minmax(0, 9rem) 1fr 2.5rem"
					>
						{@render row(e)}
					</a>
				{:else}
					<div
						class="grid items-center gap-2 rounded-sm px-1 py-px"
						style="grid-template-columns: minmax(0, 9rem) 1fr 2.5rem"
					>
						{@render row(e)}
					</div>
				{/if}
			{/each}
		</div>
	</div>
{/if}
