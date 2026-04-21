<script lang="ts">
	import { X } from '@lucide/svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';

	interface Props {
		image: ObjectImage;
		alt: string;
		onClose: () => void;
	}

	let { image, alt, onClose }: Props = $props();

	const fullSrc = $derived(`/data/v1/images/full/${image.file}`);

	function onKeyDown(event: KeyboardEvent) {
		if (event.key === 'Escape') onClose();
	}
</script>

<svelte:window onkeydown={onKeyDown} />

<!-- Desktop: offset from the 380px left sidebar so the detail panel stays visible.
     Mobile (<md): full viewport. Attribution overlays the image bottom; capped at
     a third of the viewport so long credit strings don't dominate. -->
<div
	role="dialog"
	aria-modal="true"
	aria-label={alt}
	class="fixed inset-0 z-[100] md:left-[380px] flex items-center justify-center bg-black/85 backdrop-blur-sm"
>
	<!-- Backdrop click area: full panel, below the image.  Uses a button so the
	     interaction is keyboard-accessible even though the Escape key is the
	     primary close path. -->
	<button
		type="button"
		aria-label={m.close()}
		onclick={onClose}
		class="absolute inset-0 cursor-zoom-out"
	></button>

	<img
		src={fullSrc}
		{alt}
		class="relative z-10 max-h-[100vh] max-w-full object-contain pointer-events-none"
	/>

	<button
		type="button"
		onclick={onClose}
		aria-label={m.close()}
		class="absolute top-3 right-3 z-20 flex h-9 w-9 items-center justify-center
			rounded-full bg-black/55 text-white/90 backdrop-blur-sm
			hover:bg-black/75 hover:text-white transition-colors"
	>
		<X class="h-5 w-5" aria-hidden="true" />
	</button>

	<div
		class="absolute inset-x-0 bottom-0 z-20 max-h-[33vh] overflow-y-auto
			bg-gradient-to-t from-black/80 via-black/55 to-transparent
			px-4 pt-8 pb-3 text-sm text-white/90"
	>
		<div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
			{#if image.license_url}
				<a
					href={image.license_url}
					target="_blank"
					rel="noopener noreferrer license"
					class="underline decoration-white/40 hover:decoration-white"
				>
					{image.license}
				</a>
			{:else}
				<span>{image.license}</span>
			{/if}
			{#if image.artist}
				<span class="text-white/75">{m.image_credit_by({ artist: image.artist })}</span>
			{/if}
			<a
				href={image.source_url}
				target="_blank"
				rel="noopener noreferrer"
				class="ml-auto underline decoration-white/40 hover:decoration-white"
			>
				{m.image_view_on_commons()}
			</a>
		</div>
	</div>
</div>
