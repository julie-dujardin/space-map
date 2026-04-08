<script lang="ts">
	import type { EntityRef } from '$lib/fetch/objects/object-data';

	interface Props {
		entities: EntityRef[];
	}

	let { entities }: Props = $props();
</script>

<span class="text-muted-foreground flex flex-wrap justify-end gap-x-1">
	{#each entities as entity (entity.name)}
		<span class="whitespace-nowrap">
			{#if entity.wikipedia}
				<a
					href={entity.wikipedia}
					target="_blank"
					rel="noopener noreferrer"
					class="underline hover:text-foreground">{entity.name}</a
				>
			{:else}
				{entity.name}
			{/if}
		</span>
	{/each}
</span>
