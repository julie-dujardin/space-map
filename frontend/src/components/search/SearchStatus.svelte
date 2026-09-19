<!--
  A search list with nothing to list, in the one voice every search on the site
  speaks: the first page loading, the index down, the search unset for this
  build, or a query that matched nothing.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';

	// Varied bar widths so skeleton rows read as real text, not a grid.
	const SKELETON_ROWS = [82, 64, 73, 58, 78, 67, 71, 60];

	let {
		status,
		query
	}: {
		status: 'loading' | 'error' | 'unavailable' | 'empty';
		query: string;
	} = $props();
</script>

{#if status === 'error'}
	<div role="alert" class="px-3 py-10 text-center">
		<div class="mb-1 text-sm text-foreground">{m.search_error()}</div>
		<div class="text-xs text-muted-foreground">{m.search_error_hint()}</div>
	</div>
{:else if status === 'unavailable'}
	<div class="px-3 py-10 text-center">
		<div class="text-sm text-foreground">{m.search_catalog_unavailable()}</div>
	</div>
{:else if status === 'loading'}
	<!-- Same metrics as ResultRow so the list doesn't jump when hits land. -->
	<ul class="px-2" aria-hidden="true">
		{#each SKELETON_ROWS as w, i (i)}
			<li class="flex items-center gap-3 px-4 py-2">
				<Skeleton class="size-9 shrink-0" style="animation-delay: {i * 80}ms" />
				<div class="flex min-w-0 flex-1 flex-col gap-1.5">
					<Skeleton class="h-3 rounded" style="width: {w}%; animation-delay: {i * 80}ms" />
					<Skeleton
						class="h-2.5 rounded opacity-70"
						style="width: {w - 25}%; animation-delay: {i * 80}ms"
					/>
				</div>
			</li>
		{/each}
	</ul>
{:else}
	<div class="px-3 py-10 text-center">
		<div class="mb-1 text-sm text-foreground">{m.search_no_results()}</div>
		{#if query.trim()}
			<div class="text-xs text-muted-foreground">
				{m.search_no_results_for({ query: query.trim() })}
			</div>
		{/if}
	</div>
{/if}
