<script lang="ts">
	import { getContext } from 'svelte';
	import type { FragmentOf } from '$lib/fetch/objects/object-data';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { applyGroup, serializeUrl } from '$lib/state/url';

	interface Props {
		/** Always a group link (primary_type 'group'); shares FragmentOf's shape. */
		link: FragmentOf;
		label: string;
	}
	let { link, label }: Props = $props();

	const appState = getContext<AppState | undefined>('appState');

	let href = $derived(
		appState ? serializeUrl(applyGroup(appState.view, link.primary_id, link.name)) : undefined
	);

	function open(e: MouseEvent) {
		if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
		if (!appState) return;
		e.preventDefault();
		// Already on a member craft — open the mission page without moving the
		// camera (MapPage's mission effect only flies in from outside).
		appState.setGroup(link.primary_id, link.name);
	}
</script>

<a
	{href}
	onclick={open}
	class="border-border/60 bg-muted/40 hover:bg-muted/70 pointer-events-auto flex items-center gap-3 rounded-md border p-2.5"
>
	<div class="flex min-w-0 flex-col gap-0.5">
		<span class="text-muted-foreground text-[10px] uppercase">{label}</span>
		<span class="truncate text-sm font-medium">{link.name}</span>
	</div>
</a>
