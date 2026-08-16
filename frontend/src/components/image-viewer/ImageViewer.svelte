<script lang="ts">
	import { getContext, mount, onDestroy, unmount } from 'svelte';
	import 'photoswipe/style.css';
	import type PhotoSwipeT from 'photoswipe';
	import * as m from '$lib/paraglide/messages.js';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';
	import {
		fetchImageMetadata,
		imageMetadataText,
		variantUrl,
		type ImageMetadata
	} from '$lib/fetch/objects/images';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { ShelfLink } from '$lib/fetch/objects/galleries';
	import ImageViewerCaption, { type Attribution } from './ImageViewerCaption.svelte';

	interface Props {
		images: ObjectImage[];
		alt: string;
		/** What the picture on screen is of, when the shelf mixes subjects. The
		 *  caption is mounted outside the tree, so the link arrives resolved. */
		subjectLink?: (image: ObjectImage) => ShelfLink | undefined;
	}

	let { images, alt, subjectLink }: Props = $props();

	const appState = getContext<AppState>('appState');

	/** Read rather than repeated: the sidebar's width is `--detail-panel`, and
	 *  PhotoSwipe needs it as a number. */
	function panelWidth(): number {
		const value = getComputedStyle(document.documentElement).getPropertyValue('--detail-panel');
		return parseFloat(value) || 0;
	}

	// Plain `let` (not $state) so the lifecycle effect tracks only
	// `imageIndex`, not our own ref mutations.
	let pswp: PhotoSwipeT | null = null;
	// `pswp` is only assigned after `import('photoswipe')` resolves, so
	// without `opening` a fast re-entry (double-tap, remount mid-import)
	// would spawn a second instance. `destroyed` cancels an in-flight open
	// if the component unmounts before the import lands.
	let opening = false;
	let destroyed = false;

	$effect(() => {
		const idx = appState.view.imageIndex;
		if (idx !== null && !pswp && !opening) {
			void open(idx);
		} else if (idx === null && pswp) {
			// Null the ref before calling close() so the close-event handler
			// doesn't bounce setImage(null) right back at us.
			const inst = pswp;
			pswp = null;
			inst.close();
		} else if (idx !== null && pswp && idx !== pswp.currIndex) {
			// External setImage while already open: slide to the requested
			// index. The `change` listener fires setImage(idx) back, a no-op.
			pswp.goTo(idx);
		}
	});

	onDestroy(() => {
		// destroy() (not close()) so an unmount-mid-viewer doesn't leave a
		// hide-animation playing in detached DOM. Null the ref first: destroy()
		// fires 'close', whose handler would otherwise push a redundant state.
		destroyed = true;
		if (pswp) {
			const inst = pswp;
			pswp = null;
			inst.destroy();
		}
	});

	async function open(initialIndex: number) {
		opening = true;
		try {
			const PhotoSwipe = (await import('photoswipe')).default;
			if (destroyed || appState.view.imageIndex === null) return;

			const inst = new PhotoSwipe({
				dataSource: images.map(toSlideData),
				index: initialIndex,
				loop: false,
				wheelToZoom: true,
				mainClass: 'pswp-space-map',
				closeTitle: m.close(),
				zoomTitle: m.image_zoom(),
				arrowPrevTitle: m.image_previous(),
				arrowNextTitle: m.image_next(),
				errorMsg: m.image_error(),
				// Desktop reserves the start edge for the object sidebar; tell
				// PhotoSwipe the inset width so its image fit math doesn't
				// oversize past the visible viewer area.
				getViewportSizeFn: () => ({
					x: window.matchMedia('(min-width: 768px)').matches
						? Math.max(0, window.innerWidth - panelWidth())
						: window.innerWidth,
					y: window.innerHeight
				})
			});

			inst.on('uiRegister', () => {
				inst.ui?.registerElement({
					name: 'space-map-caption',
					appendTo: 'root',
					onInit: (rootEl) => attachCaption(rootEl, inst)
				});
			});

			// setImage uses replaceState while the viewer is open, so paging
			// through a gallery doesn't grow browser history.
			inst.on('change', () => {
				if (pswp) appState.setImage(inst.currIndex);
			});

			// pswp is already null when we initiated the close ourselves.
			inst.on('close', () => {
				if (pswp) {
					pswp = null;
					appState.setImage(null);
				}
			});

			pswp = inst;
			inst.init();
		} finally {
			opening = false;
		}
	}

	function toSlideData(image: ObjectImage) {
		// srcset lets the browser pick the right variant by viewport/DPR;
		// PhotoSwipe just passes these attributes to the <img> verbatim.
		const labels = (['s', 'm', 'xl'] as const).filter((l) => image.variants[l]);
		const dims = { s: 512, m: 1024, xl: 4096 } as const;
		const srcsetParts = labels
			.map((l) => {
				const url = variantUrl(image, l);
				return url ? `${url} ${dims[l]}w` : null;
			})
			.filter((s): s is string => s !== null);
		const largest = labels[labels.length - 1];
		const smallest = labels[0];
		return {
			src: largest ? variantUrl(image, largest) : undefined,
			srcset: srcsetParts.length > 1 ? srcsetParts.join(', ') : undefined,
			msrc: smallest ? variantUrl(image, smallest) : undefined,
			width: image.width,
			height: image.height,
			alt
		};
	}

	// --- caption (Svelte component mounted into PhotoSwipe's DOM) --------------

	// PhotoSwipe is recreated per open, so this resets between viewer sessions
	// (fine: sessions are short and metadata is small).
	const metadataCache = new Map<string, Promise<ImageMetadata | null>>();

	function getMetadata(image: ObjectImage): Promise<ImageMetadata | null> {
		let p = metadataCache.get(image.file);
		if (!p) {
			p = fetchImageMetadata(image).catch(() => null);
			metadataCache.set(image.file, p);
		}
		return p;
	}

	function attachCaption(root: HTMLElement, inst: PhotoSwipeT) {
		root.className = 'pswp-sm-caption-root pswp__hide-on-close';

		// $state proxy so prop mutations propagate into the mounted component.
		const captionState: {
			image: ObjectImage | null;
			attribution: Attribution | null;
			subject: ShelfLink | null;
		} = $state({
			image: null,
			attribution: null,
			subject: null
		});

		const captionApp = mount(ImageViewerCaption, {
			target: root,
			props: captionState
		});

		// Bumped per render so a slow fetch for a prior slide can't overwrite
		// the caption for the slide the user is now on.
		let fetchToken = 0;

		async function render() {
			const idx = inst.currIndex;
			const image = images[idx];
			if (!image) return;
			captionState.image = image;
			captionState.attribution = null;
			captionState.subject = subjectLink?.(image) ?? null;

			const token = ++fetchToken;
			const meta = await getMetadata(image);
			if (token !== fetchToken) return;

			captionState.attribution = meta ? extractAttribution(meta) : null;
		}

		inst.on('change', render);
		render();

		inst.on('destroy', () => unmount(captionApp));
	}

	function extractAttribution(meta: ImageMetadata): Attribution {
		return {
			license: meta.license?.name,
			license_url: meta.license?.url,
			artist: imageMetadataText(meta.artist),
			// A multilang fallback to an arbitrary language would be unreadable,
			// so only the user's own locale is picked (bare strings still show).
			description: imageMetadataText(meta.description, true),
			date: meta.date
		};
	}
</script>

<style>
	:global(.pswp) {
		-webkit-backdrop-filter: blur(10px);
		backdrop-filter: blur(10px);
	}

	/* Vaul/bits-ui Dialog sets `pointer-events: none` on a body-level wrapper
	   to block outside-dialog interaction. PhotoSwipe is a sibling of the
	   drawer and inherits it, so touches fall through to the canvas.
	   Re-assert `auto` to restore hit-testing. */
	:global(.pswp.pswp-space-map) {
		pointer-events: auto;
	}

	/* Desktop: leave the sidebar's width clear at the start edge. Drop the
	   default `width: 100%` too, or the overlay overflows past the viewport. */
	@media (min-width: 768px) {
		:global(.pswp.pswp-space-map) {
			inset-inline-start: var(--detail-panel);
			inset-inline-end: 0;
			width: auto;
		}
	}

	/* Mobile merges description + credits into one full-width blurred bar;
	   desktop splits them into two pills side-by-side. */
	:global(.pswp-space-map .pswp-sm-caption-root) {
		position: absolute;
		inset-inline: 0;
		bottom: 0;
		z-index: 10;
		display: flex;
		flex-direction: column;
		pointer-events: none;
		background: rgba(0, 0, 0, 0.55);
		-webkit-backdrop-filter: blur(10px);
		backdrop-filter: blur(10px);
	}
	@media (min-width: 768px) {
		:global(.pswp-space-map .pswp-sm-caption-root) {
			flex-direction: row;
			align-items: flex-end;
			background: none;
			-webkit-backdrop-filter: none;
			backdrop-filter: none;
		}
	}

	:global(.pswp-space-map .pswp-sm-caption-desc-wrap) {
		pointer-events: auto;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		width: 100%;
		padding: 0.625rem 0 0;
		font-size: 0.875rem;
		line-height: 1.25;
		color: rgba(255, 255, 255, 0.85);
	}
	@media (min-width: 768px) {
		:global(.pswp-space-map .pswp-sm-caption-desc-wrap) {
			width: fit-content;
			max-width: 50%;
			padding: 0.625rem 0;
			background: rgba(0, 0, 0, 0.55);
			-webkit-backdrop-filter: blur(10px);
			backdrop-filter: blur(10px);
		}
	}

	/* max-height goes on the viewport, not the ScrollArea root: the root has
	   no definite height, so a percentage height there would resolve to auto
	   and content would spill instead of scrolling. */
	:global(.pswp-space-map .pswp-sm-caption-scroll [data-slot='scroll-area-viewport']) {
		max-height: 3lh;
		overscroll-behavior: contain;
	}
	:global(.pswp-space-map .pswp-sm-caption-scroll.is-expanded [data-slot='scroll-area-viewport']) {
		max-height: 40vh;
	}

	/* The 1rem inset matches the text under it. */
	:global(.pswp-space-map .pswp-sm-caption-subject) {
		align-self: flex-start;
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
		margin: 0 1rem;
		font-size: 0.75rem;
		font-weight: 500;
		color: rgba(255, 255, 255, 0.85);
		text-decoration: none;
	}
	:global(.pswp-space-map .pswp-sm-caption-subject:hover) {
		color: #fff;
		text-decoration: underline;
	}

	:global(.pswp-space-map .pswp-sm-caption-desc) {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding: 0 1rem;
	}
	:global(.pswp-space-map .pswp-sm-caption-desc p) {
		margin: 0;
	}

	:global(.pswp-space-map .pswp-sm-caption-toggle) {
		align-self: flex-start;
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
		margin: 0 1rem;
		padding: 0;
		font-size: 0.75rem;
		color: rgba(255, 255, 255, 0.6);
		background: none;
		border: 0;
		cursor: pointer;
	}
	:global(.pswp-space-map .pswp-sm-caption-toggle:hover) {
		color: #fff;
	}

	:global(.pswp-space-map .pswp-sm-caption-credits) {
		pointer-events: auto;
		display: flex;
		flex-wrap: nowrap;
		align-items: center;
		gap: 0.375rem;
		width: 100%;
		padding: 0.5rem 1rem 0.625rem;
		font-size: 11px;
		line-height: 1.1;
		color: rgba(255, 255, 255, 0.75);
		white-space: nowrap;
		overflow: hidden;
		justify-content: end;
	}
	@media (min-width: 768px) {
		:global(.pswp-space-map .pswp-sm-caption-credits) {
			align-self: flex-end;
			margin-inline-start: auto;
			max-width: 50%;
			width: auto;
			padding: 0.25rem 0.5rem;
			background: rgba(0, 0, 0, 0.55);
			-webkit-backdrop-filter: blur(10px);
			backdrop-filter: blur(10px);
			border-start-start-radius: 2px;
		}
	}
	:global(.pswp-space-map .pswp-sm-caption-credits a) {
		color: inherit;
		text-decoration: underline;
		text-decoration-color: rgba(255, 255, 255, 0.4);
	}
	:global(.pswp-space-map .pswp-sm-caption-credits a:hover) {
		color: #fff;
		text-decoration-color: #fff;
	}
	:global(.pswp-space-map .pswp-sm-caption-artist) {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	:global(.pswp-space-map .pswp-sm-caption-sep) {
		color: rgba(255, 255, 255, 0.4);
	}
</style>
