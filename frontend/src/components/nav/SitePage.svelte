<!--
  The frame a document page and its sub-pages share: the site row over one
  scrolling column on the site's shared width, so a title keeps its place as the
  reader moves between pages.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import SiteNav from './SiteNav.svelte';
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

<!-- html/body lock overflow for the 3D map, so the page owns its scroll — and
     the row scrolls with it. A scrollbar that narrowed only the body would
     shift the column off the row, and `stable` holds the gutter on pages short
     enough not to scroll, so the column sits still between pages. -->
<div class="h-dvh overflow-y-auto bg-bg text-text [scrollbar-gutter:stable]">
	<SiteNav {current} class="sticky top-0 z-10" />

	<main class="{SITE_COLUMN} pt-10 pb-[calc(2.5rem+var(--safe-bottom))]">
		<h1 class="{SITE_GUTTER} mb-8 text-2xl font-semibold">{title}</h1>
		{#if bleed}
			{@render children()}
		{:else}
			<div class={SITE_GUTTER}>{@render children()}</div>
		{/if}
	</main>
</div>
