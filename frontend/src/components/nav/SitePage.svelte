<!--
  The frame a document page and its sub-pages share: the site row over one
  scrolling column on the site's shared width, so a title keeps its place as the
  reader moves between pages.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import SiteNav, { SITE_COLUMN, type NavPage } from './SiteNav.svelte';

	interface Props {
		current: NavPage;
		title: string;
		children: Snippet;
	}

	let { current, title, children }: Props = $props();
</script>

<!-- html/body lock overflow for the 3D map, so the page owns its scroll — and
     the row scrolls with it. A scrollbar that narrowed only the body would
     shift the column off the row, and `stable` holds the gutter on pages short
     enough not to scroll, so the column sits still between pages. -->
<div class="h-dvh overflow-y-auto bg-bg text-text [scrollbar-gutter:stable]">
	<SiteNav {current} class="sticky top-0 z-10" />

	<main class="{SITE_COLUMN} pt-10 pb-[calc(2.5rem+var(--safe-bottom))]">
		<h1 class="mb-8 text-2xl font-semibold">{title}</h1>
		{@render children()}
	</main>
</div>
