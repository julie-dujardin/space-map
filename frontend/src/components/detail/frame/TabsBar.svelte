<script lang="ts">
	// The drawer's tab bar. The tab table and the budget/promotion deriveds
	// stay in the drawer, which owns the URL they scrub.
	import * as Tabs from '$lib/components/ui/tabs/index.js';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import { formatCompactNumber } from '$lib/format/quantities';
	import type { DrawerTab } from '$lib/state/view';
	import type { TabItem } from '../tab-visibility';

	interface Props {
		activeTab: DrawerTab;
		barTabCount: number;
		isMobile: boolean;
		inBar: (tab: DrawerTab) => boolean;
		items: TabItem[];
	}

	let { activeTab, barTabCount, isMobile, inBar, items }: Props = $props();

	// Undo shadcn's flex-1 so slack falls between tabs, not inside the shortest
	// one. The bar is a scroll container that clips at its padding box, so the
	// underline is raised and inset by the trigger's own padding: visible, and
	// underlining the label rather than the gap around it.
	const TAB_TRIGGER_CLASS = 'px-2 flex-none h-full after:-bottom-1! after:start-2! after:end-2!';

	// Nudge the bar until a deep-linked tab clears the px-4 edge inset — instant
	// on load, animated after. barTabCount re-runs it when late data reflows the bar.
	let tabBarEl = $state<HTMLElement | null>(null);
	let tabBarSettled = false;
	$effect(() => {
		void activeTab;
		void barTabCount;
		const active = tabBarEl?.querySelector<HTMLElement>('[data-state="active"]');
		if (!tabBarEl || !active) return;
		const bar = tabBarEl.getBoundingClientRect();
		const trigger = active.getBoundingClientRect();
		const start = trigger.left - bar.left - 16;
		const end = trigger.right - bar.right + 16;
		const delta = start < 0 ? start : end > 0 ? end : 0;
		if (delta) tabBarEl.scrollBy({ left: delta, behavior: tabBarSettled ? 'smooth' : 'instant' });
		tabBarSettled = true;
	});
</script>

<!-- A lone Overview tab switches nothing, so the bar goes with it. Scrolls on
     its own past the budget (mobile, which promotes nothing); without this the
     whole drawer scrolls sideways. -->
{#if barTabCount >= 2}
	<div
		bind:this={tabBarEl}
		class="pt-2 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
	>
		<!-- The list, not the scroll wrapper, carries the border/padding — a scroll
		     container's own end padding doesn't travel with overflowing content,
		     which clipped the underline and pushed the last tab flush to the edge.
		     Outer triggers drop their padding (and its underline inset) to match. -->
		<Tabs.List
			variant="line"
			class={[
				'w-full min-w-max border-b px-4',
				'[&>*:first-child]:ps-0 [&>*:first-child]:after:start-0! [&>*:last-child]:pe-0 [&>*:last-child]:after:end-0!',
				// Only a full desktop bar spreads; anywhere else the list is wider
				// than its tabs (w-full slack, or mobile's scroll room), and the
				// variant's justify-center would float them mid-bar.
				!isMobile && barTabCount >= 4 ? 'justify-between' : 'justify-start gap-2'
			]}
		>
			{#each items as item (item.tab)}
				{#if item.tab === 'overview' || inBar(item.tab)}
					<Tabs.Trigger value={item.tab} class={TAB_TRIGGER_CLASS}>
						{item.label}
						{#if item.count !== undefined}
							<Badge variant="secondary" class="text-[10px] py-0 px-1.5 h-4 leading-none">
								{formatCompactNumber(item.count)}
							</Badge>
						{/if}
					</Tabs.Trigger>
				{/if}
			{/each}
		</Tabs.List>
	</div>
{/if}
