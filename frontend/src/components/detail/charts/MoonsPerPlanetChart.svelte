<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { formatNumber } from '$lib/format/quantities';
	import { BODY_COLORS, DEFAULT_BODY_COLOR } from '$lib/constants';
	import type { GlobalGroupData } from '$lib/fetch/groups/details';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusClick, focusHref } from '$lib/state/focus-link';

	interface Props {
		/** Distance-ordered moon tallies per planet/dwarf host. */
		entries: NonNullable<GlobalGroupData['moon_counts']>;
	}
	let { entries }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	let maxCount = $derived(entries.length > 0 ? Math.max(...entries.map((e) => e.n)) : 0);

	function color(id: string): string {
		return BODY_COLORS[id] ?? DEFAULT_BODY_COLOR;
	}
</script>

{#if entries.length > 0}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.group_moons_per_planet()}</h3>
		<div class="border-border/60 border-t"></div>
		<ul class="flex flex-col gap-2 pt-1 text-sm">
			{#each entries as e (e.primary_id)}
				<li class="flex flex-col gap-1">
					<div class="flex items-baseline justify-between gap-2">
						{#if appState}
							<a
								href={focusHref(appState, e.primary_id, e.name, 'members')}
								onclick={focusClick(focusObject, e.primary_id, e.name, { tab: 'members' })}
								class="pointer-events-auto hover:text-foreground min-w-0 truncate underline"
								><span class="truncate">{e.name}</span></a
							>
						{:else}
							<span class="truncate">{e.name}</span>
						{/if}
						<span class="text-muted-foreground tabular-nums">{formatNumber(e.n)}</span>
					</div>
					<div class="bg-muted h-1.5 overflow-hidden rounded-full">
						<div
							class="h-full rounded-full"
							style:width="{maxCount > 0 ? (e.n / maxCount) * 100 : 0}%"
							style:background-color={color(e.primary_id)}
						></div>
					</div>
				</li>
			{/each}
		</ul>
	</div>
{/if}
