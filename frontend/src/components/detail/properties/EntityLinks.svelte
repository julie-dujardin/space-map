<script lang="ts">
	import { getContext } from 'svelte';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import LocateFixedIcon from '@lucide/svelte/icons/locate-fixed';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { EntityRef } from '$lib/fetch/objects/object-data';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { UrlType } from '$lib/state/view';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		entities: EntityRef[];
	}

	let { entities }: Props = $props();
	const appState = getContext<AppState | undefined>('appState');
	let truncated = $state<Record<string, boolean>>({});
	let shortened = $state<Record<string, boolean>>({});

	function focusEntity(ref: EntityRef) {
		if (!appState || !ref.primary_id || !ref.primary_type) return;
		if (ref.primary_type === 'group') {
			appState.setGroup(ref.primary_id, ref.name);
			return;
		}
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
					<span class="min-w-0 truncate" use:detectTruncation={entity.name} {...props}>
						{#if entity.primary_id && appState}
							<button
								type="button"
								onclick={() => focusEntity(entity)}
								aria-label={m.entity_focus_in_map()}
								class="underline hover:text-foreground inline-flex items-center gap-1"
								>{display}<LocateFixedIcon class="size-3 shrink-0" /></button
							>
						{:else if entity.wikipedia}
							<a
								href={entity.wikipedia}
								target="_blank"
								rel="noopener"
								class="underline hover:text-foreground inline-flex items-center gap-1"
								>{display}<ExternalLinkIcon class="size-3 shrink-0" /></a
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
