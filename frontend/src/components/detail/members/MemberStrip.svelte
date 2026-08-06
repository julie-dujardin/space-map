<script module lang="ts">
	// Slots in the overview strip's grid. At/under this count all members fit
	// here, so DetailDrawer drops the dedicated tab.
	export const STRIP_CAPACITY = 5;
</script>

<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import ArrowRightIcon from '@lucide/svelte/icons/arrow-right';
	import { memberEntryKey, type NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { pickedThumbnailUrl } from '$lib/fetch/objects/images';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';
	import {
		applyFeature,
		applyFocus,
		applyGroup,
		serializeUrl,
		urlTypeFromId
	} from '$lib/state/url';
	import { isModifiedClick } from '$lib/state/focus-link';
	import { formatCompactNumber } from '$lib/format/quantities';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
		totalCount: number;
		heading: string;
		/** Where "See all" goes — a tab of this object, or a collection page. */
		seeAllHref?: string;
		onSeeAll: () => void;
		/** Fragment lists pass false: select the piece without flying to its mesh. */
		focusMovesCamera?: boolean;
	}
	let {
		members,
		localizedNames,
		totalCount,
		heading,
		seeAllHref,
		onSeeAll,
		focusMovesCamera = true
	}: Props = $props();

	function seeAll(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		onSeeAll();
	}

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');

	// Show all when they fit; otherwise reserve the last slot for a "+N more" tile.
	let hasOverflow = $derived(totalCount > STRIP_CAPACITY);
	let shown = $derived(members.slice(0, hasOverflow ? STRIP_CAPACITY - 1 : STRIP_CAPACITY));
	let moreCount = $derived(hasOverflow ? totalCount - shown.length : 0);

	function displayName(member: NotableMemberEntry): string {
		return localizedNames?.[memberEntryKey(member)] ?? member.name;
	}

	function memberHref(member: NotableMemberEntry): string | undefined {
		if (!appState) return undefined;
		const name = displayName(member);
		if (member.group) return serializeUrl(applyGroup(appState.view, member.group, name));
		if (!member.id) return undefined;
		if (member.feature_id != null) {
			return serializeUrl(
				applyFeature(appState.view, {
					bodyId: member.id,
					featureId: member.feature_id,
					featureName: name
				})
			);
		}
		return serializeUrl(
			applyFocus(appState.view, { type: urlTypeFromId(member.id), id: member.id, name })
		);
	}

	function focusMember(e: MouseEvent, member: NotableMemberEntry) {
		if (isModifiedClick(e)) return;
		const name = displayName(member);
		// Group entry → open the group; otherwise focus the object. With no
		// appState/focusObject in context, let the href do a full-page nav.
		if (member.group) {
			if (!appState) return;
			e.preventDefault();
			appState.setGroup(member.group, name);
			return;
		}
		// A surface feature is streamed in + framed on its host body.
		if (member.feature_id != null && member.id) {
			if (!focusFeature) return;
			e.preventDefault();
			focusFeature(member.id, member.feature_id, name);
			return;
		}
		if (!focusObject || !member.id) return;
		e.preventDefault();
		focusObject(member.id, name, { moveCamera: focusMovesCamera });
	}
</script>

<div class="flex flex-col gap-1">
	<div class="flex items-baseline justify-between gap-2">
		<h3 class="text-sm font-medium min-w-0 truncate">{heading}</h3>
		{#if hasOverflow}
			<a
				href={seeAllHref}
				onclick={seeAll}
				class="pointer-events-auto text-muted-foreground hover:text-foreground inline-flex shrink-0 items-center gap-1 text-xs"
			>
				{m.members_see_all()}
				<span class="sr-only">— {heading}</span>
				<ArrowRightIcon class="size-3 rtl:rotate-180" />
			</a>
		{/if}
	</div>
	<div class="border-border/60 border-t"></div>
	<div class="grid grid-cols-5 gap-2 pt-1">
		{#each shown as member (memberEntryKey(member))}
			<a
				href={memberHref(member)}
				onclick={(e) => focusMember(e, member)}
				class="pointer-events-auto group flex min-w-0 flex-col items-center gap-1"
			>
				{#if member.thumbnail}
					<img
						src={pickedThumbnailUrl(member.thumbnail)}
						alt=""
						loading="lazy"
						decoding="async"
						class="bg-muted aspect-square w-full rounded-lg object-cover"
					/>
				{:else}
					<div
						class="bg-muted text-muted-foreground flex aspect-square w-full items-center justify-center rounded-lg text-lg font-medium"
					>
						{displayName(member).charAt(0)}
					</div>
				{/if}
				<span
					class="text-muted-foreground group-hover:text-foreground w-full truncate text-center text-xs"
				>
					{displayName(member)}
				</span>
			</a>
		{/each}
		{#if moreCount > 0}
			<a
				href={seeAllHref}
				onclick={seeAll}
				class="pointer-events-auto group flex min-w-0 flex-col items-center gap-1"
			>
				<div
					class="bg-muted text-muted-foreground group-hover:text-foreground flex aspect-square w-full items-center justify-center rounded-lg text-xs font-medium tabular-nums"
				>
					+{formatCompactNumber(moreCount)}
				</div>
				<span
					class="text-muted-foreground group-hover:text-foreground w-full truncate text-center text-xs"
				>
					{m.members_more()}
				</span>
			</a>
		{/if}
	</div>
</div>
