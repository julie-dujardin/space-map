<script lang="ts">
	// The detail panel's frame, standing in until the drawer chunk and its
	// payload arrive. A shared link names its object in the URL seconds before
	// the scene has streamed that body in, and everything the panel displaces
	// moves on the same signal — so the frame goes up at first paint and the
	// real drawer lands in the space it already holds.
	import type { TransitionConfig } from 'svelte/transition';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import HeroSkeleton from './frame/skeleton/HeroSkeleton.svelte';
	import PanelSkeleton from './frame/skeleton/PanelSkeleton.svelte';
	import TabsSkeleton from './frame/skeleton/TabsSkeleton.svelte';

	interface Props {
		/** What the URL points at — it sets how many toolbar buttons the header
		 *  row ends up carrying (see DetailDrawer's `drawerToolbar`). */
		kind: 'body' | 'feature' | 'group';
	}

	let { kind }: Props = $props();

	// Zoom (bodies only), travel (anything with a body), share, close.
	let buttonCount = $derived(kind === 'group' ? 2 : kind === 'feature' ? 3 : 4);

	// The real sheet mounts off-screen and is only pinned to its snap point on
	// the following frame, so dropping this one on the same tick leaves the
	// bottom of the screen bare for a frame. It holds a moment longer, under a
	// sheet drawn at the same place. No css and no tick: the node just stays
	// where it is.
	const hold = (_node: Element, config: TransitionConfig): TransitionConfig => config;
</script>

{#snippet toolbar()}
	<div class="flex items-center gap-1.5">
		{#each { length: buttonCount }, i (i)}
			<Skeleton class="size-9 rounded-full" />
		{/each}
	</div>
{/snippet}

<!-- Which frame shows is a CSS question here, not a matchMedia one: this
     renders server-side, where the viewport is unknown, and a frame of the
     wrong one is the reflow it exists to prevent. `min-[769px]` is DRAWER_MQ
     as a Tailwind variant — the scanner only reads literal classes. -->

<!-- The sheet at its collapsed snap: chrome only, which is where vaul opens it. -->
<div
	aria-hidden="true"
	out:hold|global={{ duration: 100 }}
	class="fixed inset-x-0 bottom-0 z-50 flex flex-col rounded-t-xl border-t bg-background shadow-lg min-[769px]:hidden"
>
	<div class="flex flex-col items-center gap-2 px-4 pt-3 pb-2">
		<div class="h-1 w-10 rounded-full bg-muted-foreground/40"></div>
		<div class="flex w-full items-center justify-between gap-2">
			<Skeleton class="h-5 w-32" />
			{@render toolbar()}
		</div>
	</div>
</div>

<aside
	aria-hidden="true"
	class="fixed top-0 start-0 z-50 hidden h-full w-[var(--detail-panel)] max-w-[90vw] flex-col border-e bg-background shadow-lg min-[769px]:flex"
>
	<div class="flex items-center justify-between gap-2 px-4 pb-2 pt-[18px]">
		<Skeleton class="h-5 w-32" />
		{@render toolbar()}
	</div>
	<HeroSkeleton />
	<TabsSkeleton />
	<div class="px-4 pt-4">
		<PanelSkeleton />
	</div>
</aside>
