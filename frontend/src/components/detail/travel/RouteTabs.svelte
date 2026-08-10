<!--
  One tab per family of trajectory, when there is more than one family to choose
  between.

  The drawer's own tab bar rather than a segmented control: the panel already
  carries three of those (when to go, how to brake, and the endpoint modes) and a
  fourth would read as a fourth setting rather than as which list is showing.

  The swing-by's tab is there before its route is, greyed with a spinner: the
  hunt takes about a second, and a tab that only appeared when it landed would
  either shove the others sideways under the reader's pointer or, worse, never be
  looked for at all.
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
		/** The active family's rows. Inside the tabs, so each tab controls a panel
		 *  that is really there. */
		children: Snippet;
	}
	let { tabs, active, onSelect, children }: Props = $props();

	// Same as the object drawer's: the trigger's padding is the gap between tabs,
	// so the outer two drop theirs and the underline follows, sitting flush with
	// the panel's own edges.
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
				// Two tabs spread across the panel would read as two halves of a
				// segmented control; three or more fill the bar as a bar.
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
						<LoaderCircleIcon class="size-3 shrink-0 animate-spin" />
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
