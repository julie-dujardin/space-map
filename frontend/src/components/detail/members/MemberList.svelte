<script lang="ts">
	import { getContext } from 'svelte';
	import type { NotableMemberEntry } from '$lib/fetch/groups/details';
	import { pickedThumbnailUrl } from '$lib/fetch/objects/images';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { applyFocus, applyGroup, serializeUrl, urlTypeFromId } from '$lib/state/url';
	import { formatQuantity } from '$lib/format/quantities';
	import { m } from '$lib/paraglide/messages';
	import type { ProbeVisitKind } from '$lib/fetch/objects/object-data';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
		/** Fragment lists pass false: select the piece without flying to its mesh. */
		focusMovesCamera?: boolean;
	}
	let { members, localizedNames, focusMovesCamera = true }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	function displayName(member: NotableMemberEntry): string {
		return localizedNames?.[member.id ?? member.group ?? ''] ?? member.name;
	}

	function memberHref(member: NotableMemberEntry): string | undefined {
		if (!appState) return undefined;
		const name = displayName(member);
		if (member.group) return serializeUrl(applyGroup(appState.view, member.group, name));
		if (!member.id) return undefined;
		return serializeUrl(
			applyFocus(appState.view, { type: urlTypeFromId(member.id), id: member.id, name })
		);
	}

	function focusMember(e: MouseEvent, member: NotableMemberEntry) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		const name = displayName(member);
		if (member.group) {
			if (!appState) return;
			e.preventDefault();
			appState.setGroup(member.group, name);
			return;
		}
		if (!focusObject || !member.id) return;
		e.preventDefault();
		focusObject(member.id, name, { moveCamera: focusMovesCamera });
	}

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
		atmospheric: m.probe_kind_atmospheric
	};

	/** Arrival–end years; a same-year visit collapses to one, an ongoing one
	 *  keeps an open dash. */
	function visitYears(visit: NonNullable<NotableMemberEntry['visit']>): string {
		const from = visit.arrival.slice(0, 4);
		const to = visit.end?.slice(0, 4);
		if (to === from) return from;
		return `${from}–${to ?? ''}`;
	}
</script>

<div class="flex flex-col gap-1">
	<ul class="flex flex-col">
		{#each members as member (member.id ?? member.group)}
			{@const year = discoveryYear(member)}
			<li>
				<a
					href={memberHref(member)}
					onclick={(e) => focusMember(e, member)}
					class="pointer-events-auto hover:bg-muted/40 -mx-1 flex items-center gap-3 rounded-md px-1 py-2"
				>
					{#if member.thumbnail}
						<img
							src={pickedThumbnailUrl(member.thumbnail)}
							alt=""
							loading="lazy"
							decoding="async"
							class="bg-muted size-10 shrink-0 rounded-md object-cover"
						/>
					{:else}
						<div
							class="bg-muted text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-md text-sm font-medium"
						>
							{displayName(member).charAt(0)}
						</div>
					{/if}
					<span class="min-w-0 flex-1 truncate text-sm font-medium">{displayName(member)}</span>
					<span class="flex shrink-0 flex-col items-end text-xs tabular-nums">
						{#if member.visit}
							<span>{KIND_LABEL[member.visit.kind]()}</span>
							<span class="text-muted-foreground">{visitYears(member.visit)}</span>
						{:else}
							{#if member.diameter_km != null}
								<span>{formatQuantity({ value: member.diameter_km, unit: 'kilometre' }, true)}</span
								>
							{/if}
							{#if year}
								<span class="text-muted-foreground">{year}</span>
							{/if}
							{#if member.diameter_km == null && !year}
								<span class="text-muted-foreground">–</span>
							{/if}
						{/if}
					</span>
				</a>
			</li>
		{/each}
	</ul>
</div>
