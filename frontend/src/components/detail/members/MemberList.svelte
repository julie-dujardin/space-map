<script lang="ts">
	import { getContext } from 'svelte';
	import MemberRow, { memberFigures } from './MemberRow.svelte';
	import { memberClick, memberDisplayName, memberHref } from './member-link';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';
	import {
		memberEntryKey,
		type NotableMemberEntry,
		type ProbeVisitKind
	} from '$lib/fetch/objects/object-data';
	import { m } from '$lib/paraglide/messages';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
		/** Localized labels for the bodies a collection's probe rows name. */
		targetNames?: Record<string, string>;
		/** Fragment lists pass false: select the piece without flying to its mesh. */
		focusMovesCamera?: boolean;
	}
	let { members, localizedNames, targetNames, focusMovesCamera = true }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');

	let nav = $derived({ appState, focusObject, focusFeature, moveCamera: focusMovesCamera });

	/** Discovery year from the first_obs proxy (YYYY-MM-DD or YYYY). */
	function discoveryYear(member: NotableMemberEntry): string | undefined {
		const year = member.first_obs?.slice(0, 4);
		return year && Number.isFinite(parseInt(year, 10)) ? year : undefined;
	}

	const KIND_LABEL: Record<ProbeVisitKind, () => string> = {
		flyby: m.probe_kind_flyby,
		orbiter: m.probe_kind_orbiter,
		lander: m.probe_kind_lander,
		rover: m.probe_kind_rover,
		impactor: m.probe_kind_impactor,
		sample: m.probe_kind_sample,
		atmospheric: m.probe_kind_atmospheric,
		observer: m.probe_kind_observer
	};

	/** Arrival–end years; a same-year visit collapses to one, an ongoing one
	 *  keeps an open dash. */
	function visitYears(visit: { arrival: string; end?: string }): string {
		const from = visit.arrival.slice(0, 4);
		const to = visit.end?.slice(0, 4);
		if (to === from) return from;
		return `${from}–${to ?? ''}`;
	}
</script>

<div class="flex flex-col gap-1">
	<ul class="flex flex-col">
		{#each members as member (memberEntryKey(member))}
			{@const year = discoveryYear(member)}
			{@const name = memberDisplayName(member, localizedNames)}
			<MemberRow
				{name}
				thumbnail={member.thumbnail}
				href={memberHref(appState, member, name)}
				onclick={memberClick(nav, member, name)}
				valuesClass="tabular-nums"
				valuesWrap={member.visits !== undefined}
			>
				{#if member.visits}
					{#each member.visits as target (target.id)}
						<span class="whitespace-nowrap">
							{targetNames?.[target.id] ?? target.name}
							<span class="text-muted-foreground">{visitYears(target)}</span>
						</span>
					{/each}
				{:else if member.visit}
					<span>{KIND_LABEL[member.visit.kind]()}</span>
					<span class="text-muted-foreground">{visitYears(member.visit)}</span>
				{:else}
					{@render memberFigures({ diameter_km: member.diameter_km, year })}
				{/if}
			</MemberRow>
		{/each}
	</ul>
</div>
