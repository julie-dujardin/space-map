<script lang="ts">
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { EntityRef } from '$lib/fetch/objects/object-data';

	interface Props {
		entities: EntityRef[];
	}

	let { entities }: Props = $props();
	let truncated = $state<Record<string, boolean>>({});
	let shortened = $state<Record<string, boolean>>({});

	function detectTruncation(node: HTMLElement, name: string) {
		// Measure with a hidden clone that always contains the full name,
		// so switching to short_name doesn't cause a feedback loop.
		const probe = document.createElement('span');
		probe.textContent = name;
		probe.style.cssText = 'visibility:hidden;position:absolute;white-space:nowrap';

		function check() {
			node.appendChild(probe);
			const natural = probe.scrollWidth;
			const available = node.clientWidth;
			truncated[name] = natural > available;
			shortened[name] = natural > available * 1.2; // shorten only beyond 20% truncation
			probe.remove();
		}
		check();
		const observer = new ResizeObserver(check);
		observer.observe(node);
		return {
			destroy: () => {
				observer.disconnect();
				probe.remove();
			}
		};
	}
</script>

<span class="text-muted-foreground flex flex-wrap justify-end gap-x-2">
	{#each entities as entity (entity.name)}
		{@const display = shortened[entity.name] && entity.short_name ? entity.short_name : entity.name}
		<Tooltip.Root disabled={!truncated[entity.name]}>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<span class="min-w-0 truncate" use:detectTruncation={entity.name} {...props}>
						{#if entity.wikipedia}
							<a
								href={entity.wikipedia}
								target="_blank"
								rel="noopener"
								class="underline hover:text-foreground">{display}</a
							>
						{:else}
							{display}
						{/if}
					</span>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content>{entity.name}</Tooltip.Content>
		</Tooltip.Root>
	{/each}
</span>
