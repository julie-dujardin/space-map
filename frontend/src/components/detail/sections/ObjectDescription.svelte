<script lang="ts">
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import ChevronUpIcon from '@lucide/svelte/icons/chevron-up';
	import Link from './kit/Link.svelte';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		extract?: string;
		wikipediaUrl?: string;
		/** Characters shown before "Read more". Secondary blurbs (a selected
		 *  quadrangle) take half the object default so they don't crowd out the
		 *  list they sit above. */
		truncateLength?: number;
	}

	let { extract, wikipediaUrl, truncateLength = 400 }: Props = $props();
	let expanded = $state(false);

	let needsTruncation = $derived(extract ? extract.length > truncateLength : false);
	let displayText = $derived(
		extract
			? expanded || !needsTruncation
				? extract
				: extract.slice(0, truncateLength).replace(/\s+\S*$/, '') + '…'
			: ''
	);
</script>

{#if extract}
	<div class="flex flex-col gap-2">
		{#each displayText.split('\n').filter((p) => p.trim()) as paragraph, i (i)}
			<p class="text-sm leading-relaxed">{paragraph}</p>
		{/each}
		{#if needsTruncation || wikipediaUrl}
			<div class="flex items-center gap-3 text-xs text-muted-foreground">
				{#if needsTruncation}
					<button
						class="flex items-center gap-1 hover:text-foreground"
						onclick={() => (expanded = !expanded)}
					>
						{expanded ? m.show_less() : m.read_more()}
						{#if expanded}
							<ChevronUpIcon class="size-3.5" />
						{:else}
							<ChevronDownIcon class="size-3.5" />
						{/if}
					</button>
				{/if}
				{#if wikipediaUrl}
					<span class="ms-auto">
						{m.source_prefix()}
						<Link href={wikipediaUrl} external>{m.source_wikipedia_name()}</Link>
					</span>
				{/if}
			</div>
		{/if}
	</div>
{/if}
