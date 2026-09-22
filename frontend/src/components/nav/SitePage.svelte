<!--
  The frame a document page and its sub-pages share: the site row over one
  scrolling column on the site's shared width, so a title keeps its place as the
  reader moves between pages.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import SiteNav from './SiteNav.svelte';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { SITE_COLUMN, SITE_GUTTER, type NavPage } from './site';

	interface Props {
		/** Left out on a page the row does not list, such as the error page. */
		current?: NavPage;
		title: string;
		/** Hand the children the full column and let them gutter themselves, for
		 *  a page carrying something that wants every pixel of the width. */
		bleed?: boolean;
		children: Snippet;
	}

	let { current, title, bleed = false, children }: Props = $props();
</script>

<!-- html/body lock overflow for the 3D map, so the page owns its scroll. The row
     sits outside the scroller rather than sticking inside it: sticky does not
     hold against a scroll area's viewport, and an overlay scrollbar under the
     row keeps the column in the same place on every page, long or short. -->
<div class="flex h-dvh flex-col bg-bg text-text">
	<SiteNav {current} class="shrink-0" />

	<ScrollArea class="min-h-0 flex-1">
		<main class="{SITE_COLUMN} pt-10 pb-[calc(2.5rem+var(--safe-bottom))]">
			<h1 class="{SITE_GUTTER} mb-8 text-2xl font-semibold">{title}</h1>
			{#if bleed}
				{@render children()}
			{:else}
				<div class={SITE_GUTTER}>{@render children()}</div>
			{/if}
		</main>
	</ScrollArea>
</div>
