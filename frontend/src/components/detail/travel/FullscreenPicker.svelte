<!--
  The shell a picker takes on a phone, in place of its popover: the whole
  screen, a titled bar with a way back, and the picker's own body below it.

  Mirrors the map's search overlay rather than the popover it replaces — a
  floating card positioned against a trigger has nowhere to grow on a screen
  the width of the panel that opened it.

  Portalled to the body because the phone layout puts the panel inside Vaul's
  drawer, which is transformed as it snaps: `fixed` inside a transformed
  ancestor measures from that ancestor, not the screen, so the overlay would
  hang off the bottom by however far the drawer had been dragged.

  It has to take its own pointer events back, since the open drawer turns them
  off body-wide and the portal puts this outside the subtree vaul re-enables.
-->
<script lang="ts">
	import { getContext, type Snippet } from 'svelte';
	import type { MapCover } from '$lib/state/map-cover.svelte';
	import { Portal } from 'bits-ui';
	import XIcon from '@lucide/svelte/icons/x';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		title: string;
		onClose: () => void;
		children: Snippet;
	}
	let { title, onClose, children }: Props = $props();

	// Opaque and fullscreen for as long as it is mounted.
	getContext<MapCover>('mapCover').hold();
</script>

<!-- Escape closes it, as it would the popover this stands in for. -->
<svelte:window
	onkeydown={(e: KeyboardEvent) => {
		if (e.key === 'Escape') onClose();
	}}
/>

<Portal>
	<div
		class="bg-popover pointer-events-auto fixed inset-0 z-50 flex flex-col pt-[var(--safe-top)] pe-[var(--safe-end)] pb-[var(--safe-bottom)] ps-[var(--safe-start)]"
		role="dialog"
		aria-modal="true"
		aria-label={title}
	>
		<div class="border-border flex h-[46px] shrink-0 items-center gap-2 border-b px-3">
			<span class="min-w-0 flex-1 truncate text-sm font-medium">{title}</span>
			<button
				type="button"
				onclick={onClose}
				aria-label={m.close()}
				class="text-muted-foreground hover:bg-accent hover:text-foreground rounded-full p-1 transition-colors"
			>
				<XIcon class="size-4" />
			</button>
		</div>
		<div class="flex min-h-0 flex-1 flex-col p-3">
			{@render children()}
		</div>
	</div>
</Portal>
