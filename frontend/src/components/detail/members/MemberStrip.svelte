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
	import { memberDisplayName } from './member-link';
	import { targetClick, targetHref } from '$lib/state/focus-link';
	import { pickedThumbnailUrl } from '$lib/fetch/objects/images';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';
	import { isModifiedClick } from '$lib/modified-click';
	import { formatCompactNumber } from '$lib/format/quantities';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
		totalCount: number;
		heading: string;
		/** Where "See all" goes — a tab of this object, or a collection page. */
		seeAllHref?: string;
		onSeeAll: () => void;
		/** Keep the link when everything already fits: the probes tab carries
		 *  the exploration blurb and the craft lineup, which the strip cannot
		 *  show, and a promoted tab has no other way in. */
		alwaysSeeAll?: boolean;
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
		alwaysSeeAll = false,
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

	let nav = $derived({ appState, focusObject, focusFeature, moveCamera: focusMovesCamera });
</script>

<div class="flex flex-col gap-1">
	<div class="flex items-baseline justify-between gap-2">
		<h3 class="text-sm font-medium min-w-0 truncate">{heading}</h3>
		{#if hasOverflow || alwaysSeeAll}
			<a
				href={seeAllHref}
				onclick={seeAll}
				class="text-muted-foreground hover:text-foreground inline-flex shrink-0 items-center gap-1 text-xs"
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
			{@const name = memberDisplayName(member, localizedNames)}
			<a
				href={targetHref(appState, member, name)}
				onclick={targetClick(nav, member, name)}
				class="group flex min-w-0 flex-col items-center gap-1"
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
						{name.charAt(0)}
					</div>
				{/if}
				<span
					class="text-muted-foreground group-hover:text-foreground w-full truncate text-center text-xs"
				>
					{name}
				</span>
			</a>
		{/each}
		{#if moreCount > 0}
			<a href={seeAllHref} onclick={seeAll} class="group flex min-w-0 flex-col items-center gap-1">
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
