<script lang="ts">
	import { getContext } from 'svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { applyGroup, serializeUrl } from '$lib/state/url';
	import { formatCompactNumber } from '$lib/format/quantities';

	interface Props {
		slug: string;
		name: string;
		n?: number;
		/** Highlights the chip for the focused group. */
		active?: boolean;
	}
	let { slug, name, n = 0, active = false }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

	let href = $derived(appState ? serializeUrl(applyGroup(appState.view, slug, name)) : undefined);

	// Plain left-click swaps in-app; modifier-clicks fall through to the browser.
	function onClick(e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		e.preventDefault();
		appState.setGroup(slug, name);
	}
</script>

<a
	{href}
	onclick={onClick}
	aria-current={active ? 'page' : undefined}
	class="flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors {active
		? 'border-foreground/40 bg-muted/60'
		: 'border-border/60 hover:bg-muted/60'}"
>
	<span class="font-medium">{name}</span>
	{#if n > 0}
		<span class="text-muted-foreground tabular-nums">{formatCompactNumber(n)}</span>
	{/if}
</a>
