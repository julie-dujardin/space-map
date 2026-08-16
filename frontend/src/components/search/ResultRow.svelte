<script lang="ts">
	import { getContext } from 'svelte';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import LayersIcon from '@lucide/svelte/icons/layers';
	import { formatCompactNumber } from '$lib/format/quantities';
	import type { SearchHit } from '$lib/search/client';
	import type { AppState } from '$lib/state/app-state.svelte';
	import {
		applyFeature,
		applyFocus,
		applyGroup,
		serializeUrl,
		urlTypeFromId
	} from '$lib/state/url';
	import { isModifiedClick } from '$lib/state/focus-link';

	type Props = {
		hit: SearchHit;
		name: string;
		secondary: string;
		thumbnail?: string;
		/** DOM id referenced by the combobox input's aria-activedescendant. */
		id: string;
		active: boolean;
		onselect: () => void;
		onhover: () => void;
		/** Right-aligned value tied to the active sort (size/brightness/…). */
		metric?: { value: string; unit?: string };
	};

	let { hit, name, secondary, thumbnail, id, active, onselect, onhover, metric }: Props = $props();

	// Collection pages (constellations, organizations, orbit classes, …) read
	// as a navigable group: stacked-card thumbnail, member count, and a
	// chevron signalling "opens a page".

	const appState = getContext<AppState | undefined>('appState');

	let href = $derived.by(() => {
		if (!appState) return undefined;
		const view = appState.view;
		if (hit.kind === 'feature')
			return serializeUrl(
				applyFeature(view, { bodyId: hit.body_id, featureId: hit.feature_id, featureName: name })
			);
		if (hit.kind === 'group') return serializeUrl(applyGroup(view, hit.slug, name));
		return serializeUrl(applyFocus(view, { type: urlTypeFromId(hit.id), id: hit.id, name }));
	});

	// Plain left-click picks in-session, which also collapses the search; a
	// modified click opens the destination in a new tab and leaves it open.
	function onClick(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		onselect();
	}
</script>

<!-- Combobox pattern: the row is an option, keyboard focus stays on the input
     (tabindex -1 keeps dozens of rows out of the tab order). `role="option"`
     replaces the link role for assistive tech; the href stays for the pointer. -->
<a
	{href}
	{id}
	role="option"
	aria-selected={active}
	tabindex={-1}
	class="w-full text-start px-4 py-2 flex items-center gap-3 transition-colors {active
		? 'bg-neutral-200 dark:bg-accent'
		: 'hover:bg-neutral-200 dark:hover:bg-accent'}"
	onmouseenter={onhover}
	onclick={onClick}
>
	<span class="relative size-9 shrink-0">
		{#if hit.kind === 'group'}
			<!-- offset cards behind the thumbnail to read as a stack -->
			<span class="absolute inset-0 translate-x-1 -translate-y-0.5 rounded-md bg-muted opacity-40"
			></span>
			<span class="absolute inset-0 translate-x-0.5 -translate-y-px rounded-md bg-muted opacity-70"
			></span>
		{/if}
		{#if thumbnail}
			<img
				src={thumbnail}
				alt=""
				loading="lazy"
				decoding="async"
				class="absolute inset-0 size-9 rounded-md object-cover bg-muted"
			/>
		{:else}
			<span class="absolute inset-0 size-9 rounded-md bg-muted"></span>
		{/if}
		{#if hit.kind === 'group'}
			<span
				class="absolute -end-1 -bottom-1 grid size-4 place-items-center rounded bg-popover text-foreground ring-2 ring-popover"
			>
				<LayersIcon class="size-2.5" />
			</span>
		{/if}
	</span>

	<span class="flex flex-col gap-0.5 min-w-0 flex-1">
		<span dir="auto" class="text-sm text-foreground truncate">{name}</span>
		{#if secondary}
			<span dir="auto" class="text-xs text-muted-foreground truncate">{secondary}</span>
		{/if}
	</span>

	{#if hit.kind === 'group'}
		<span class="flex shrink-0 items-center gap-1.5 text-muted-foreground">
			<span class="text-xs tabular-nums text-foreground"
				>{formatCompactNumber(hit.member_count)}</span
			>
			<ChevronRightIcon class="size-4 rtl:rotate-180" />
		</span>
	{:else if metric}
		<span class="shrink-0 text-end font-mono text-xs tabular-nums text-muted-foreground">
			<span class="text-foreground">{metric.value}</span>{#if metric.unit}<span class="ms-0.5"
					>{metric.unit}</span
				>{/if}
		</span>
	{/if}
</a>
