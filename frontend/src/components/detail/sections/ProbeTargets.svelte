<!--
  Where the craft was sent: one row per target body, what it did there, and
  when — most recent stop first. The strip along the map keeps the
  event-by-event telling.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import MemberRow from '../members/MemberRow.svelte';
	import type { TargetVisit } from '$lib/probes/target-list';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { focusClick, focusHref } from '$lib/state/focus-link';

	interface Props {
		visits: TargetVisit[];
	}

	let { visits }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
</script>

{#if visits.length > 0}
	<ul class="flex flex-col">
		{#each visits as visit (visit.objectId ?? visit.target.name)}
			{@const id = visit.objectId}
			<MemberRow
				name={visit.target.name}
				thumbnail={visit.target.thumbnail}
				href={id ? focusHref(appState, id, visit.target.name) : undefined}
				onclick={id ? focusClick(focusObject, id, visit.target.name) : undefined}
				valuesClass="max-w-[55%]"
			>
				{#each visit.activities as activity (activity.label + activity.dates)}
					<span class="max-w-full truncate">{activity.label}</span>
					<span class="text-muted-foreground max-w-full truncate tabular-nums"
						>{activity.dates}</span
					>
				{/each}
			</MemberRow>
		{/each}
	</ul>
{/if}
