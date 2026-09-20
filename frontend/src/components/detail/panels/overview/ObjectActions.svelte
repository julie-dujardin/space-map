<!--
  What a reader can do with the object in view, as a row of labelled tiles at
  the head of its overview. The drawer's own button row carries the same few
  actions as bare icons in the corner, where they read as window chrome; named
  and in the panel they read as places to go.

  Only the ones this object has: a trip has to be plannable, a comparison needs
  something to stand the body beside, panoramas need someone to have stood there.
-->
<script lang="ts">
	import { getContext, type Component } from 'svelte';
	import { resolve } from '$app/paths';
	import NavigationIcon from '@lucide/svelte/icons/navigation';
	import Columns2Icon from '@lucide/svelte/icons/columns-2';
	import MountainIcon from '@lucide/svelte/icons/mountain';
	import Share2Icon from '@lucide/svelte/icons/share-2';
	import { ZoomInIcon, ZoomOutIcon } from '@lucide/svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { PositionedBody } from '$lib/types/objects';
	import { compareSeed } from '$lib/compare/presets';
	import { panoramaHref } from '$lib/state/panorama-link';
	import { travelEntry } from '$lib/travel/travel-entry';
	import { isModifiedClick } from '$lib/modified-click';

	interface Props {
		/** The object the panel is about. */
		body: PositionedBody;
		/** Set on a surface feature's panel: the trip ends in that named place. */
		featureId?: number | null;
		/** A feature stands on the body rather than being it, so the actions that
		 *  are about the body as a whole sit this one out. */
		isFeature?: boolean;
		/** Surface panoramas taken on this body. */
		hasPanoramas?: boolean;
		/** Frames the object, or pulls back out to its system once it is framed.
		 *  Absent where the panel stands on a page with no camera to move. */
		onFocus?: () => void;
		/** Whether the camera is already on the object, which is what turns the
		 *  focus action around. */
		isMinimized?: boolean;
		onShare: () => void;
	}

	let {
		body,
		featureId = null,
		isFeature = false,
		hasPanoramas = false,
		onFocus,
		isMinimized = false,
		onShare
	}: Props = $props();

	const ctx = getContext<ContextManager | undefined>('ctx');
	const appState = getContext<AppState | undefined>('appState');

	interface Action {
		key: string;
		label: string;
		Icon: Component<{ class?: string }>;
		/** Set on the actions that go somewhere, so a modified click opens a
		 *  real URL. */
		href?: string;
		onclick?: (e: MouseEvent) => void;
		/** The one action drawn filled — the object's own next step. */
		primary?: boolean;
	}

	let travel = $derived(travelEntry(ctx, appState, body.data, featureId));
	let comparison = $derived(isFeature ? null : compareSeed(body.data));

	let actions = $derived.by<Action[]>(() => {
		const out: Action[] = [];
		if (travel) {
			const entry = travel;
			out.push({
				key: 'travel',
				label: m.object_action_directions(),
				Icon: NavigationIcon,
				href: entry.href,
				primary: true,
				onclick: (e) => {
					if (isModifiedClick(e) || !appState) return;
					e.preventDefault();
					appState.setNav(entry.departure, entry.destination);
				}
			});
		}
		if (comparison) {
			out.push({
				key: 'compare',
				label: m.compare_page_title(),
				Icon: Columns2Icon,
				// `on` lands the row on this body's own page: banded by size, a set
				// it joins from below opens pages away from it otherwise.
				href: `${resolve('/compare')}?m=${comparison.join(',')}&on=${body.data.id}`
			});
		}
		if (hasPanoramas && !isFeature) {
			out.push({
				key: 'panoramas',
				label: m.nav_panoramas(),
				Icon: MountainIcon,
				href: panoramaHref(body.data.id)
			});
		}
		out.push({
			key: 'share',
			label: m.share(),
			Icon: Share2Icon,
			onclick: onShare
		});
		if (onFocus) {
			out.push({
				key: 'focus',
				label: isMinimized ? m.object_action_zoom_out() : m.object_action_focus(),
				Icon: isMinimized ? ZoomOutIcon : ZoomInIcon,
				onclick: onFocus
			});
		}
		return out;
	});

	// Equal columns, but no wider than a tile needs: a panel with two actions on
	// it reads as two buttons, not as a row with holes in it.
	const tile = 'flex min-w-0 max-w-24 flex-1 flex-col items-center gap-1.5 text-center';
	const disc = 'flex size-11 items-center justify-center rounded-full transition-colors';
	const label = 'text-[11px] leading-tight text-muted-foreground';
</script>

<div class="flex items-start gap-1">
	{#each actions as action (action.key)}
		{@const discClass = `${disc} ${
			action.primary
				? 'bg-foreground text-background hover:bg-foreground/90'
				: 'bg-secondary text-secondary-foreground hover:bg-accent'
		}`}
		{#if action.href}
			<a href={action.href} onclick={action.onclick} class={tile}>
				<span class={discClass}><action.Icon class="size-5" /></span>
				<span class={label}>{action.label}</span>
			</a>
		{:else}
			<button type="button" onclick={action.onclick} class="{tile} cursor-pointer">
				<span class={discClass}><action.Icon class="size-5" /></span>
				<span class={label}>{action.label}</span>
			</button>
		{/if}
	{/each}
</div>
