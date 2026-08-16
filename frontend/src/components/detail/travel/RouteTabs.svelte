<!--
  One tab per family of trajectory.

  A tab bar rather than a segmented control: the panel already has three of
  those, and a fourth would read as a setting rather than as which list shows.

  The swing-by tab appears greyed with a spinner before its route exists —
  waiting for it to land would shift the other tabs under the reader's pointer.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import LoaderCircleIcon from '@lucide/svelte/icons/loader-circle';
	import * as Tabs from '$lib/components/ui/tabs/index.js';
	import type { RouteFamily, RouteTab } from '$lib/travel/route-families';
	import { familyLabel } from './route-labels';

	interface Props {
		tabs: readonly RouteTab[];
		active: RouteFamily | null;
		onSelect: (family: RouteFamily) => void;
		/** The active family's rows, inside the tabs so each tab controls a real
		 *  panel. */
		children: Snippet;
	}
	let { tabs, active, onSelect, children }: Props = $props();

	// Trigger padding doubles as the gap between tabs, so the outer two drop
	// theirs and the underline stays flush with the panel edges.
	const TRIGGER_CLASS = 'px-2 flex-none h-full after:-bottom-1! after:start-2! after:end-2!';
</script>

<Tabs.Root
	value={active ?? ''}
	onValueChange={(value: string) => onSelect(value as RouteFamily)}
	class="w-full"
>
	<!-- Scrolls rather than wraps, so a locale that names three families at length
	     cannot push the trajectories down the panel. -->
	<div class="overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
		<Tabs.List
			variant="line"
			aria-label={m.travel_trajectories()}
			class={[
				'w-full min-w-max border-b',
				'[&>*:first-child]:ps-0 [&>*:first-child]:after:start-0! [&>*:last-child]:pe-0 [&>*:last-child]:after:end-0!',
				// Two tabs spread full-width would read as a segmented control, not
				// a bar.
				tabs.length >= 3 ? 'justify-between' : 'justify-start gap-2'
			]}
		>
			{#each tabs as tab (tab.family)}
				<Tabs.Trigger
					value={tab.family}
					disabled={tab.loading}
					title={tab.loading ? m.travel_assist_searching() : undefined}
					class={TRIGGER_CLASS}
				>
					{#if tab.loading}
						<LoaderCircleIcon class="size-3 shrink-0 animate-spin" aria-hidden="true" />
						<span class="sr-only">{m.travel_assist_searching()}</span>
					{/if}
					{familyLabel(tab.family)}
				</Tabs.Trigger>
			{/each}
		</Tabs.List>
	</div>

	<Tabs.Content value={active ?? ''} class="flex flex-col gap-2">
		{@render children()}
	</Tabs.Content>
</Tabs.Root>
