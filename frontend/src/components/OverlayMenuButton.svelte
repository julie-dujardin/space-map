<script lang="ts">
	import XIcon from '@lucide/svelte/icons/x';
	import { Dialog } from 'bits-ui';
	import { getContext, hasContext, type Component, type Snippet } from 'svelte';
	import type { MapCover } from '$lib/state/map-cover.svelte';
	import * as Popover from '$lib/components/ui/popover';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		title: string;
		Icon: Component<{ class?: string }>;
		/** Overrides the map's glass trigger for chrome on a light surface. */
		triggerClass?: string;
		children: Snippet;
	}

	let { title, Icon, triggerClass, children }: Props = $props();

	let open = $state(false);
	let isMobile = $state(false);

	$effect(() => {
		const mq = window.matchMedia('(max-width: 767px)');
		isMobile = mq.matches;
		const onChange = (e: MediaQueryListEvent) => (isMobile = e.matches);
		mq.addEventListener('change', onChange);
		return () => mq.removeEventListener('change', onChange);
	});

	// A fullscreen panel can pause the map it covers.
	const mapCover = hasContext('mapCover') ? getContext<MapCover>('mapCover') : null;
	mapCover?.hold(() => {
		const mobile = isMobile;
		const shown = open;
		return mobile && shown;
	});

	const mapGlass = `flex items-center justify-center
		w-10 h-10 md:w-8 md:h-8 rounded-full
		bg-black/40 backdrop-blur-md hover:bg-black/55
		text-white transition-colors cursor-pointer`;

	const buttonClass = $derived(triggerClass ?? mapGlass);
</script>

{#if isMobile}
	<!-- bits-ui Dialog gives the fullscreen mobile panel real focus management
	     (trap on open, restore to trigger on close) and makes the covered app inert. -->
	<Dialog.Root bind:open>
		<Dialog.Trigger class={buttonClass} {title} aria-label={title}>
			<Icon class="size-5" />
		</Dialog.Trigger>
		<Dialog.Portal>
			<Dialog.Overlay class="fixed inset-0 z-[69] bg-black/40" />
			<Dialog.Content
				class="fixed inset-0 z-[70] overflow-y-auto bg-background pt-[var(--safe-top)] pb-[var(--safe-bottom)] ps-[var(--safe-start)] pe-[var(--safe-end)] outline-none"
			>
				<Dialog.Title class="sr-only">{title}</Dialog.Title>
				<Dialog.Close
					class="absolute top-3 end-3 z-10 inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-accent transition-colors cursor-pointer"
					aria-label={m.close()}
				>
					<XIcon class="size-5" />
				</Dialog.Close>
				{@render children()}
			</Dialog.Content>
		</Dialog.Portal>
	</Dialog.Root>
{:else}
	<Popover.Root bind:open>
		<Popover.Trigger class={buttonClass} {title} aria-label={title}>
			<Icon class="size-4" />
		</Popover.Trigger>
		<Popover.Content
			side="bottom"
			align="end"
			sideOffset={8}
			class="w-80 max-h-[80dvh] overflow-hidden p-0"
		>
			{@render children()}
		</Popover.Content>
	</Popover.Root>
{/if}
