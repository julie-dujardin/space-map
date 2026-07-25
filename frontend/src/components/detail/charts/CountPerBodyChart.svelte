<script lang="ts">
	import { getContext } from 'svelte';
	import { formatNumber } from '$lib/format/quantities';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusClick, focusHref } from '$lib/state/focus-link';
	import type { DrawerTab } from '$lib/state/view';

	/** One tally per host body — moons per planet, features per body. */
	export interface CountPerBodyEntry {
		name: string;
		primary_type: 'object';
		primary_id: string;
		n: number;
	}

	interface Props {
		entries: CountPerBodyEntry[];
		title: string;
		/** Tab the row opens on the host body. */
		tab?: Exclude<DrawerTab, 'overview'>;
		/** Body id → localized label, when the bundle ships one. */
		names?: Record<string, string>;
	}
	let { entries, title, tab, names }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	let maxCount = $derived(entries.length > 0 ? Math.max(...entries.map((e) => e.n)) : 0);

	function label(e: CountPerBodyEntry): string {
		return names?.[e.primary_id] ?? e.name;
	}

	function color(id: string): string {
		return BODY_COLORS[id] ?? DEFAULT_BODY_COLOR;
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
		<h3 class="text-sm font-medium">{title}</h3>
		<div class="border-border/60 border-t"></div>
		<div class="mt-1 flex flex-col gap-[3px]">
			{#each entries as e (e.primary_id)}
				{#if appState}
					<a
						href={focusHref(appState, e.primary_id, label(e), tab)}
						onclick={focusClick(focusObject, e.primary_id, label(e), { tab })}
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
