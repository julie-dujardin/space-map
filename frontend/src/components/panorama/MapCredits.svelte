<!--
  The maps a page of traverses is drawn on, credited under them: one line per
  author, with the wording their terms ask for.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { LayerCredit } from '$lib/flatmap/layers';
	import Link from '../detail/sections/kit/Link.svelte';

	interface Props {
		credits: LayerCredit[];
		class?: string;
	}

	let { credits, class: className = '' }: Props = $props();
</script>

{#if credits.length}
	<footer class="border-t border-border pt-4 text-xs/5 text-muted-foreground {className}">
		<span>{m.attribution_map()}:</span>
		{#each credits as credit (credit.organisation)}
			<div>
				<Link href={credit.source} external icon={false}>{credit.organisation}</Link>
				{#if credit.attribution}<span class="text-muted-subtle ms-1">({credit.attribution})</span
					>{/if}
			</div>
		{/each}
	</footer>
{/if}
