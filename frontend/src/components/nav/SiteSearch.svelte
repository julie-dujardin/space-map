<!--
  The phone form of search on the site pages: the map's full search, in a
  dialog over the page. A pick opens the map.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import SearchIcon from '@lucide/svelte/icons/search';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { isSearchEnabled, localizedName } from '$lib/search/client';
	import { searchHitHref } from '$lib/state/page-href';
	import * as Sheet from '$lib/components/ui/sheet/index.js';
	import SearchBar from '../search/SearchBar.svelte';

	let open = $state(false);
</script>

{#if isSearchEnabled()}
	<Sheet.Root bind:open>
		<Sheet.Trigger
			class="flex h-10 w-10 cursor-pointer items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
			aria-label={m.search_placeholder()}
		>
			<SearchIcon class="size-5" />
		</Sheet.Trigger>
		<!-- On the site menu's tier, over everything the page holds. -->
		<Sheet.Content
			side="top"
			showCloseButton={false}
			overlayClass="z-[69]"
			class="z-[70] gap-0 p-0 data-[side=top]:h-dvh data-[side=top]:border-b-0"
		>
			<Sheet.Title class="sr-only">{m.search_placeholder()}</Sheet.Title>
			<SearchBar
				onSelect={(hit) => goto(searchHitHref(hit, localizedName(hit, getLocale())))}
				onClose={() => (open = false)}
			/>
		</Sheet.Content>
	</Sheet.Root>
{/if}
