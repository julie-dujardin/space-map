<script lang="ts">
	import { getContext } from 'svelte';
	import Link from './Link.svelte';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { EntityRef } from '$lib/fetch/objects/object-data';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusFeature, FocusObject } from '$lib/state/focusable';
	import { targetClick, targetHref, type LinkTarget } from '$lib/state/focus-link';

	interface Props {
		entities: EntityRef[];
	}

	let { entities }: Props = $props();
	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');
	let nav = $derived({ appState, focusObject, focusFeature });
	let truncated = $state<Record<string, boolean>>({});
	let shortened = $state<Record<string, boolean>>({});

	/** A ref carries its id split in two; the shared router wants it whole. Which
	 *  prefix it is stays the id's business, so no type is named here. */
	function entityTarget(ref: EntityRef): LinkTarget {
		if (!ref.primary_id || !ref.primary_type) return {};
		if (ref.primary_type === 'group') return { group: ref.primary_id };
		const id = `${ref.primary_type}-${ref.primary_id}`;
		if (ref.secondary_type === 'feature' && ref.secondary_id) {
			return { id, feature_id: parseInt(ref.secondary_id, 10) };
		}
		return { id };
	}

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
	{#each entities as entity (`${entity.name}|${entity.wikipedia ?? ''}|${entity.primary_type ?? ''}|${entity.primary_id ?? ''}`)}
		{@const display = shortened[entity.name] && entity.short_name ? entity.short_name : entity.name}
		<Tooltip.Root disabled={!truncated[entity.name]}>
			<Tooltip.Trigger>
				{#snippet child({ props })}
					<span class="min-w-0 max-w-full" use:detectTruncation={entity.name} {...props}>
						{#if entity.primary_id && appState}
							<Link
								href={targetHref(appState, entityTarget(entity), entity.name)}
								onclick={targetClick(nav, entityTarget(entity), entity.name)}
								class="inline-flex max-w-full items-center gap-1 align-bottom"
								><span class="truncate">{display}</span></Link
							>
						{:else if entity.wikipedia}
							<Link href={entity.wikipedia} external class="max-w-full align-bottom"
								><span class="truncate">{display}</span></Link
							>
						{:else}
							<span class="truncate block">{display}</span>
						{/if}
					</span>
				{/snippet}
			</Tooltip.Trigger>
			<Tooltip.Content>{entity.name}</Tooltip.Content>
		</Tooltip.Root>
	{/each}
</span>
