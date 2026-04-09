<script lang="ts">
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { EntityRef } from '$lib/fetch/objects/object-data';

	interface Props {
		entities: EntityRef[];
	}

	let { entities }: Props = $props();
	let truncated = $state<Record<string, boolean>>({});

	function detectTruncation(node: HTMLElement, name: string) {
		function check() {
			truncated[name] = node.scrollWidth > node.clientWidth;
		}
		check();
		const observer = new ResizeObserver(check);
		observer.observe(node);
		return { destroy: () => observer.disconnect() };
	}
</script>

<span class="text-muted-foreground flex flex-wrap justify-end gap-x-1">
	{#each entities as entity (entity.name)}
		<Tooltip.Root disabled={!truncated[entity.name]}>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<span class="max-w-48 truncate" use:detectTruncation={entity.name} {...props}>
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
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content>{entity.name}</Tooltip.Content>
		</Tooltip.Root>
	{/each}
</span>
