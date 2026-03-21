<script lang="ts">
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
	<div class="flex flex-col gap-1">
		<p class="text-sm leading-relaxed whitespace-pre-line">{displayText}</p>
		{#if needsTruncation}
			<button
				class="text-xs text-muted-foreground hover:text-foreground self-start"
				onclick={() => (expanded = !expanded)}
			>
				{expanded ? 'Show less' : 'Read more'}
			</button>
		{/if}
	</div>
{/if}
