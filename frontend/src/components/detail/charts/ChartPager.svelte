<script lang="ts">
	/** Prev/next control for the group page's bar charts. Renders nothing for a
	 *  single page, so a caller can hand it any list. */

	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		page: number;
		pageCount: number;
		onpage: (page: number) => void;
	}
	let { page, pageCount, onpage }: Props = $props();
</script>

{#if pageCount > 1}
	<div class="text-muted-foreground flex items-center gap-1 text-xs">
		<button
			type="button"
			onclick={() => onpage(Math.max(0, page - 1))}
			disabled={page === 0}
			aria-label={m.search_prev_page()}
			class="hover:text-foreground pointer-events-auto rounded p-0.5 transition disabled:opacity-30"
		>
			<ChevronLeftIcon class="size-3.5 rtl:rotate-180" />
		</button>
		<span class="tabular-nums">{page + 1}/{pageCount}</span>
		<button
			type="button"
			onclick={() => onpage(Math.min(pageCount - 1, page + 1))}
			disabled={page === pageCount - 1}
			aria-label={m.search_next_page()}
			class="hover:text-foreground pointer-events-auto rounded p-0.5 transition disabled:opacity-30"
		>
			<ChevronRightIcon class="size-3.5 rtl:rotate-180" />
		</button>
	</div>
{/if}
