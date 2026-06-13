<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { FragmentOf } from '$lib/fetch/objects/object-data';
	import { pickedThumbnailUrl } from '$lib/fetch/objects/images';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { FocusObject } from '$lib/state/focusable';
	import { applyFocus, applyGroup, serializeUrl, urlTypeFromId } from '$lib/state/url';

	interface Props {
		fragmentOf: FragmentOf;
	}
	let { fragmentOf }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');

	let href = $derived.by(() => {
		if (!appState) return undefined;
		const { name, primary_type, primary_id } = fragmentOf;
		return primary_type === 'group'
			? serializeUrl(applyGroup(appState.view, primary_id, name))
			: serializeUrl(
					applyFocus(appState.view, { type: urlTypeFromId(primary_id), id: primary_id, name })
				);
	});

	function open(e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		const { name, primary_type, primary_id } = fragmentOf;
		if (primary_type === 'group') {
			if (!appState) return;
			e.preventDefault();
			appState.setGroup(primary_id, name);
			return;
		}
		if (!focusObject) return;
		e.preventDefault();
		// Parent comet's mesh isn't worth flying to — just select it.
		focusObject(primary_id, name, { moveCamera: false });
	}
</script>

<a
	{href}
	onclick={open}
	class="border-border/60 bg-muted/40 hover:bg-muted/70 pointer-events-auto flex items-center gap-3 rounded-md border p-2.5"
>
	{#if fragmentOf.thumbnail}
		<img
			src={pickedThumbnailUrl(fragmentOf.thumbnail)}
			alt=""
			loading="lazy"
			decoding="async"
			class="bg-muted size-12 shrink-0 rounded-lg object-cover"
		/>
	{/if}
	<div class="flex min-w-0 flex-col gap-0.5">
		<span class="text-muted-foreground text-[10px] uppercase">{m.fragment_of()}</span>
		<span class="truncate text-sm font-medium">{fragmentOf.name}</span>
	</div>
</a>
