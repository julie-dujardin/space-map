<script lang="ts">
	import { getContext } from 'svelte';
	import Link from './Link.svelte';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { EntityRef } from '$lib/fetch/objects/object-data';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { applyFeature, applyFocus, serializeUrl } from '$lib/state/url';
	import { groupClick, groupHref } from '$lib/state/focus-link';
	import { isModifiedClick } from '$lib/modified-click';
	import { UrlType } from '$lib/state/view';

	interface Props {
		entities: EntityRef[];
	}

	let { entities }: Props = $props();
	const appState = getContext<AppState | undefined>('appState');
	let truncated = $state<Record<string, boolean>>({});
	let shortened = $state<Record<string, boolean>>({});

	function focusEntity(ref: EntityRef) {
		if (!appState || !ref.primary_id || !ref.primary_type) return;
		const bodyId = `${ref.primary_type}-${ref.primary_id}`;
		if (ref.secondary_type === 'feature' && ref.secondary_id) {
			appState.setFeature({
				bodyId,
				featureId: parseInt(ref.secondary_id, 10),
				featureName: ref.name
			});
		} else {
			const urlType = ref.primary_type === 'spkid' ? UrlType.SmallBody : UrlType.Body;
			appState.setFocus({ type: urlType, id: bodyId, name: ref.name });
		}
	}

	function entityHref(ref: EntityRef): string | undefined {
		if (!appState || !ref.primary_id || !ref.primary_type) return undefined;
		if (ref.primary_type === 'group') return groupHref(appState, ref.primary_id, ref.name);
		const bodyId = `${ref.primary_type}-${ref.primary_id}`;
		if (ref.secondary_type === 'feature' && ref.secondary_id) {
			return serializeUrl(
				applyFeature(appState.view, {
					bodyId,
					featureId: parseInt(ref.secondary_id, 10),
					featureName: ref.name
				})
			);
		}
		const urlType = ref.primary_type === 'spkid' ? UrlType.SmallBody : UrlType.Body;
		return serializeUrl(applyFocus(appState.view, { type: urlType, id: bodyId, name: ref.name }));
	}

	/** A group ref goes through the shared handler; a body or feature one has no
	 *  `focusObject` here, so it rewrites the URL and lets the drawer follow. */
	function entityClick(ref: EntityRef): (e: MouseEvent) => void {
		if (ref.primary_type === 'group' && ref.primary_id)
			return groupClick(appState, ref.primary_id, ref.name);
		return (e) => {
			if (isModifiedClick(e)) return;
			e.preventDefault();
			focusEntity(ref);
		};
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
								href={entityHref(entity)}
								onclick={entityClick(entity)}
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
