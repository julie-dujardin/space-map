<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		extract?: string;
		wikipediaUrl?: string;
	}

	let { extract, wikipediaUrl }: Props = $props();
	let expanded = $state(false);

	const TRUNCATE_LENGTH = 400;
	let needsTruncation = $derived(extract ? extract.length > TRUNCATE_LENGTH : false);
	let displayText = $derived(
		extract
			? expanded || !needsTruncation
				? extract
				: extract.slice(0, TRUNCATE_LENGTH).replace(/\s+\S*$/, '') + '…'
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
					<button class="hover:text-foreground" onclick={() => (expanded = !expanded)}>
						{expanded ? m.show_less() : m.read_more()}
					</button>
				{/if}
				{#if wikipediaUrl}
					<span class:ml-auto={needsTruncation}>
						{m.source_prefix()}
						<a
							href={wikipediaUrl}
							target="_blank"
							rel="noopener"
							class="underline hover:text-foreground"
						>
							{m.source_wikipedia_name()}
						</a>
					</span>
				{/if}
			</div>
		{/if}
	</div>
{/if}
