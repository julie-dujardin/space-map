<script lang="ts">
	/** The Rings tab's hero: the best picture of the ring system, selected from
	 *  the "Rings of X" article the panel already cites. */

	import * as m from '$lib/paraglide/messages.js';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';
	import { fetchImageMetadata, imageMetadataText, variantUrl } from '$lib/fetch/objects/images';

	interface Props {
		image: ObjectImage;
		alt: string;
	}

	let { image, alt }: Props = $props();

	/** The two widths the drawer can ask for; the source is far larger than the
	 *  panel and the small variant alone blurs on a retina screen. */
	let srcset = $derived(
		(['s', 'm'] as const)
			.map((label) => {
				const url = variantUrl(image, label);
				return url ? `${url} ${label === 's' ? 512 : 1024}w` : null;
			})
			.filter((part) => part !== null)
			.join(', ')
	);

	/** Who to credit. Read from the image's own metadata rather than exported
	 *  beside it: the credit rides in the bytes of the variant already on
	 *  screen, so it costs a cache hit. */
	let credit = $state<string | undefined>(undefined);
	$effect(() => {
		const current = image;
		credit = undefined;
		let live = true;
		fetchImageMetadata(current)
			.then((meta) => {
				// First line only: Commons credits often run to a second paragraph
				// of processing and restoration notes, which is a caption's worth
				// of text on its own. The Commons link carries the whole record.
				if (live) credit = imageMetadataText(meta?.artist)?.split('\n')[0];
			})
			.catch((error) => console.debug(`Ring hero: no credit for ${current.file}`, error));
		return () => {
			live = false;
		};
	});
</script>

<figure class="flex flex-col gap-1">
	<!-- Contained rather than cropped: these run from a 2.4:1 Cassini mosaic to
	     a square JWST frame, and filling the box would cut the rings out of the
	     tall ones. The black backdrop is the sky the pictures are already mostly
	     made of, so the letterboxing doesn't read as a gap. -->
	<img
		src={variantUrl(image, 's')}
		{srcset}
		sizes="(min-width: 768px) 350px, 90vw"
		width={image.width}
		height={image.height}
		{alt}
		loading="lazy"
		decoding="async"
		class="max-h-52 w-full rounded-md bg-black/40 object-contain"
	/>
	<figcaption class="flex flex-wrap items-baseline gap-x-1 px-1 text-[10px] text-muted-foreground">
		{#if credit}<span>{credit} ·</span>{/if}
		<a
			href={image.source_url}
			target="_blank"
			rel="noopener noreferrer"
			class="underline-offset-2 hover:text-foreground hover:underline"
			>{m.image_view_on_commons()}</a
		>
	</figcaption>
</figure>
