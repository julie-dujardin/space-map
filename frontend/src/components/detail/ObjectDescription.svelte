<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		extract?: string;
	}

	let { extract }: Props = $props();
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
		{#each displayText.split('\n') as paragraph, i (i)}
			<p class="text-sm leading-relaxed">{paragraph}</p>
		{/each}
		{#if needsTruncation}
			<button
				class="text-xs text-muted-foreground hover:text-foreground self-start"
				onclick={() => (expanded = !expanded)}
			>
				{expanded ? m.show_less() : m.read_more()}
			</button>
		{/if}
	</div>
{/if}
