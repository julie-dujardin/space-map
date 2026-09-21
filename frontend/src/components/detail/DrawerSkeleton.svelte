<script lang="ts">
	// The detail panel's frame, standing in until the drawer chunk and its
	// payload arrive. A shared link names its object in the URL seconds before
	// the scene has streamed that body in, and everything the panel displaces
	// moves on the same signal — so the frame goes up at first paint and the
	// real drawer lands in the space it already holds.
	//
	// What the URL already settles is drawn for real, not greyed out: the title
	// it names, and the two actions that need nothing but the page itself.
	import type { TransitionConfig } from 'svelte/transition';
	import XIcon from '@lucide/svelte/icons/x';
	import Share2Icon from '@lucide/svelte/icons/share-2';
	import { Button } from '$lib/components/ui/button/index.js';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { shareUrl } from '$lib/share';
	import * as m from '$lib/paraglide/messages.js';
	import HeroSkeleton from './frame/skeleton/HeroSkeleton.svelte';
	import PanelSkeleton from './frame/skeleton/PanelSkeleton.svelte';
	import TabsSkeleton from './frame/skeleton/TabsSkeleton.svelte';

	interface Props {
		/** What the URL points at — it sets how many toolbar buttons the header
		 *  row ends up carrying (see DetailDrawer's `drawerToolbar`). */
		kind: 'body' | 'feature' | 'group';
		/** The name the URL carries, empty until one is known. */
		title: string;
		onClose: () => void;
	}

	let { kind, title, onClose }: Props = $props();

	// Zoom (bodies only) and travel (anything with a body) wait for the scene;
	// share and close are drawn for real ahead of it.
	let pendingButtons = $derived(kind === 'group' ? 0 : kind === 'feature' ? 1 : 2);

	// The real sheet mounts off-screen and is only pinned to its snap point on
	// the following frame, so dropping this one on the same tick leaves the
	// bottom of the screen bare for a frame. It holds a moment longer, under a
	// sheet drawn at the same place. No css and no tick: the node just stays
	// where it is.
	const hold = (_node: Element, config: TransitionConfig): TransitionConfig => config;
</script>

{#snippet heading()}
	{#if title}
		<h2 class="min-w-0 flex-1 truncate text-sm font-semibold">{title}</h2>
	{:else}
		<Skeleton aria-hidden="true" class="h-5 w-32" />
	{/if}
{/snippet}

{#snippet toolbar()}
	<div class="flex items-center gap-1.5">
		{#each { length: pendingButtons }, i (i)}
			<Skeleton aria-hidden="true" class="size-9 rounded-full" />
		{/each}
		<Button
			variant="secondary"
			size="icon-lg"
			class="rounded-full"
			onclick={() => void shareUrl(title)}
		>
			<Share2Icon />
			<span class="sr-only">{m.share()}</span>
		</Button>
		<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={onClose}>
			<XIcon />
			<span class="sr-only">{m.close()}</span>
		</Button>
	</div>
{/snippet}

<!-- Which frame shows is a CSS question here, not a matchMedia one: this
     renders server-side, where the viewport is unknown, and a frame of the
     wrong one is the reflow it exists to prevent. `min-[769px]` is DRAWER_MQ
     as a Tailwind variant — the scanner only reads literal classes. -->

<!-- The sheet at its collapsed snap: chrome only, which is where vaul opens it. -->
<div
	out:hold|global={{ duration: 100 }}
	class="fixed inset-x-0 bottom-0 z-50 flex flex-col rounded-t-xl border-t bg-background shadow-lg min-[769px]:hidden"
>
	<div class="flex flex-col items-center gap-2 px-4 pt-3 pb-2">
		<div class="h-1 w-10 rounded-full bg-muted-foreground/40"></div>
		<div class="flex w-full items-center justify-between gap-2">
			{@render heading()}
			{@render toolbar()}
		</div>
	</div>
</div>

<aside
	class="fixed start-0 top-[var(--detail-top,0px)] z-50 hidden h-[calc(100%-var(--detail-top,0px))] w-[var(--detail-panel)] max-w-[90vw] flex-col border-e bg-background shadow-lg min-[769px]:flex"
>
	<div class="flex items-center justify-between gap-2 px-4 pb-2 pt-[18px]">
		{@render heading()}
		{@render toolbar()}
	</div>
	<div aria-hidden="true" class="contents">
		<HeroSkeleton />
		<TabsSkeleton />
		<div class="px-4 pt-4">
			<PanelSkeleton />
		</div>
	</div>
</aside>
