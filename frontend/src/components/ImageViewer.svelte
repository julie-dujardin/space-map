<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import 'photoswipe/style.css';
	import type PhotoSwipeT from 'photoswipe';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { ObjectImage } from '$lib/fetch/objects/object-data';
	import { fetchImageMetadata, variantUrl, type ImageMetadata } from '$lib/fetch/objects/images';
	import type { AppState } from '$lib/state/app-state.svelte';

	interface Props {
		images: ObjectImage[];
		alt: string;
	}

	let { images, alt }: Props = $props();

	const appState = getContext<AppState>('appState');

	// Plain `let` (not $state) so the lifecycle effect tracks only
	// `imageIndex` — not our own ref mutations.
	let pswp: PhotoSwipeT | null = null;
	// Synchronous gates for the async open path: `pswp` is only assigned
	// after `import('photoswipe')` resolves, so without `opening` a fast
	// re-entry (double-tap, or a remount mid-import) sees `pswp` still
	// null and spawns a second instance. `destroyed` cancels an in-flight
	// open if the component unmounts before the import lands.
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
		}
	});

	onDestroy(() => {
		// destroy() (not close()) so an unmount-mid-viewer (focus change to
		// another object, navigation away) doesn't leave a hide-animation
		// playing in detached DOM.
		destroyed = true;
		if (pswp) {
			pswp.destroy();
			pswp = null;
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
				arrowPrevTitle: m.image_previous(),
				arrowNextTitle: m.image_next()
			});

			inst.on('uiRegister', () => {
				inst.ui?.registerElement({
					name: 'space-map-caption',
					appendTo: 'root',
					onInit: (rootEl) => attachCaption(rootEl, inst)
				});
			});

			// Mirror nav into the URL. setImage uses replaceState while the
			// viewer is open, so a 10-image gallery doesn't grow history.
			inst.on('change', () => {
				if (pswp) appState.setImage(inst.currIndex);
			});

			// Esc / close button / vertical-drag / bg-click / our own close().
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
		// Build a srcset from whatever variants the bundle emitted, plus the
		// single largest URL as the canonical `src`. Browser's image picker
		// chooses the right variant from srcset based on viewport + DPR;
		// PhotoSwipe just hands the <img> these attributes verbatim.
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

	// --- caption (built inside PhotoSwipe's DOM via registerElement) -----------

	interface Attribution {
		license?: string;
		license_url?: string;
		artist?: string;
		description?: string;
	}

	// Promise cache so swiping back to a previously-viewed slide doesn't refetch.
	// Lifetime is tied to the component instance; PhotoSwipe is recreated per
	// open, so the cache resets between viewer sessions (which is fine — sessions
	// are short and metadata is small).
	const metadataCache = new Map<string, Promise<ImageMetadata | null>>();

	function getMetadata(image: ObjectImage): Promise<ImageMetadata | null> {
		let p = metadataCache.get(image.file);
		if (!p) {
			p = fetchImageMetadata(image).catch(() => null);
			metadataCache.set(image.file, p);
		}
		return p;
	}

	/** Build the caption subtree once and update its contents on `change`.
	 *  Imperative because PhotoSwipe owns this DOM tree — mounting a Svelte
	 *  child here would fight PhotoSwipe's lifecycle (re-renders during
	 *  open/close transitions, no clean teardown hook). */
	function attachCaption(root: HTMLElement, inst: PhotoSwipeT) {
		root.className = 'pswp-sm-caption-root pswp__hide-on-close';

		const descWrap = document.createElement('div');
		descWrap.className = 'pswp-sm-caption-desc-wrap';
		const descBody = document.createElement('div');
		descBody.className = 'pswp-sm-caption-desc';
		const toggleBtn = document.createElement('button');
		toggleBtn.type = 'button';
		toggleBtn.className = 'pswp-sm-caption-toggle';
		descWrap.append(descBody, toggleBtn);

		const credits = document.createElement('div');
		credits.className = 'pswp-sm-caption-credits';

		root.append(descWrap, credits);

		let expanded = false;
		// Token bumped per render so a slow metadata fetch from a prior slide
		// can't overwrite the caption for the slide the user is now on.
		let fetchToken = 0;

		function setExpanded(next: boolean) {
			expanded = next;
			descWrap.classList.toggle('is-expanded', expanded);
			toggleBtn.textContent = expanded ? m.show_less() : m.read_more();
		}

		toggleBtn.addEventListener('click', (e) => {
			e.stopPropagation();
			setExpanded(!expanded);
		});

		// Show the toggle only when the collapsed body actually overflows, or
		// when we know there are more paragraphs hidden behind the line-clamp
		// (explicit newlines in the source).
		const ro = new ResizeObserver(() => updateTruncation());
		ro.observe(descBody);

		let hasExplicitBreaks = false;

		function updateTruncation() {
			if (expanded) return;
			const overflows = descBody.scrollHeight > descBody.clientHeight + 1;
			descWrap.classList.toggle('is-truncated', overflows || hasExplicitBreaks);
		}

		function renderDescription(text: string | undefined) {
			descBody.replaceChildren();
			if (!text) {
				descWrap.style.display = 'none';
				return;
			}
			descWrap.style.display = '';
			const paragraphs = text.split('\n').filter((p) => p.trim());
			for (const p of paragraphs) {
				const el = document.createElement('p');
				el.textContent = p;
				descBody.append(el);
			}
			hasExplicitBreaks = text.includes('\n');
			updateTruncation();
		}

		function renderCredits(image: ObjectImage, attribution: Attribution | null) {
			credits.replaceChildren();
			const parts: (Node | string)[] = [];
			if (attribution?.license) {
				if (attribution.license_url) {
					const a = document.createElement('a');
					a.href = attribution.license_url;
					a.target = '_blank';
					a.rel = 'noopener noreferrer license';
					a.textContent = attribution.license;
					parts.push(a);
				} else {
					parts.push(attribution.license);
				}
			}
			if (attribution?.artist) {
				const span = document.createElement('span');
				span.className = 'pswp-sm-caption-artist';
				span.textContent = attribution.artist;
				parts.push(span);
			}
			const source = document.createElement('a');
			source.href = image.source_url;
			source.target = '_blank';
			source.rel = 'noopener noreferrer';
			source.textContent = m.image_view_on_commons();
			parts.push(source);

			parts.forEach((part, i) => {
				if (i > 0) {
					const sep = document.createElement('span');
					sep.className = 'pswp-sm-caption-sep';
					sep.setAttribute('aria-hidden', 'true');
					sep.textContent = '·';
					credits.append(sep);
				}
				credits.append(part);
			});
		}

		async function render() {
			const idx = inst.currIndex;
			const image = images[idx];
			if (!image) return;

			setExpanded(false);
			descWrap.classList.remove('is-truncated');

			const token = ++fetchToken;
			const meta = await getMetadata(image);
			if (token !== fetchToken) return;

			const attribution = meta ? extractAttribution(meta) : null;
			renderDescription(attribution?.description);
			renderCredits(image, attribution);
			updateTruncation();
		}

		inst.on('change', render);
		render();

		inst.on('destroy', () => ro.disconnect());
	}

	// --- metadata helpers -------------------------------------------------------

	function extractAttribution(meta: ImageMetadata): Attribution {
		return {
			license: meta.license?.name,
			license_url: meta.license?.url,
			artist: plainText(meta.artist),
			// For descriptions, a multilang fallback to an arbitrary language
			// would be unreadable, so we only pick the user's own locale. Bare
			// (unlocalized) strings are always shown if nothing better is available.
			description: plainText(meta.description, true)
		};
	}

	/** Resolve a trimmed multilang field to a plain-text string.
	 *
	 *  The exporter writes bare strings when Commons didn't return a multilang
	 *  blob and `{<locale>: str}` dicts (restricted to supported locales) when
	 *  it did. HTML from Commons still passes through — we strip it here.
	 *  With `strictLocale`, a dict is only resolved for the current locale;
	 *  bare strings are always returned regardless. */
	function plainText(
		value: string | Record<string, string> | undefined,
		strictLocale = false
	): string | undefined {
		if (value === undefined) return undefined;
		const raw = typeof value === 'string' ? value : pickLang(value, strictLocale);
		if (!raw) return undefined;
		// `innerHTML` parses but doesn't execute scripts (HTML5 spec); using
		// `.textContent` then gives us a safely-stripped plain-text version.
		const tmp = document.createElement('div');
		tmp.innerHTML = raw;
		for (const br of tmp.querySelectorAll('br')) br.replaceWith('\n');
		for (const block of tmp.querySelectorAll('p, div, li')) block.append('\n\n');
		const text = (tmp.textContent ?? '')
			// Collapse non-newline whitespace runs; keep newlines intact.
			.replace(/[^\S\n]+/g, ' ')
			// Normalize any run of 2+ newlines to exactly one blank line.
			.replace(/\n{2,}/g, '\n\n')
			.trim();
		return text || undefined;
	}

	function pickLang(value: Record<string, string>, strictLocale: boolean): string {
		const locale = getLocale();
		if (typeof value[locale] === 'string') return value[locale];
		if (strictLocale) return '';
		if (typeof value.en === 'string') return value.en;
		for (const v of Object.values(value)) {
			if (typeof v === 'string') return v;
		}
		return '';
	}
</script>

<style>
	/* Vaul/bits-ui Dialog in modal mode sets `pointer-events: none` on a
	   body-level wrapper to block outside-dialog interaction. PhotoSwipe is
	   appended to body as a sibling of the drawer and inherits that none
	   (pointer-events is an inherited property), which makes image-area
	   touches fall straight through to the canvas. Re-asserting `auto` here
	   restores hit-testing for every .pswp descendant that doesn't carry an
	   explicit override of its own. */
	:global(.pswp.pswp-space-map) {
		pointer-events: auto;
	}

	/* Caption container: pinned to the bottom of pswp.element, above slides.
	   Mobile merges description + credits into one full-width blurred bar;
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
		backdrop-filter: blur(10px);
		-webkit-backdrop-filter: blur(10px);
	}
	@media (min-width: 768px) {
		:global(.pswp-space-map .pswp-sm-caption-root) {
			flex-direction: row;
			align-items: flex-end;
			background: none;
			backdrop-filter: none;
			-webkit-backdrop-filter: none;
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
			backdrop-filter: blur(10px);
			-webkit-backdrop-filter: blur(10px);
		}
	}

	:global(.pswp-space-map .pswp-sm-caption-desc) {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding: 0 1rem;
		overflow: hidden;
		max-height: 3lh;
	}
	:global(.pswp-space-map .pswp-sm-caption-desc p) {
		margin: 0;
	}

	:global(.pswp-space-map .pswp-sm-caption-desc-wrap.is-expanded) {
		max-height: 40vh;
	}
	:global(.pswp-space-map .pswp-sm-caption-desc-wrap.is-expanded .pswp-sm-caption-desc) {
		max-height: none;
		overflow-y: auto;
		overscroll-behavior: contain;
		touch-action: pan-y;
		padding-right: 0.5rem;
	}

	:global(.pswp-space-map .pswp-sm-caption-toggle) {
		display: none;
		align-self: flex-start;
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
	:global(.pswp-space-map .pswp-sm-caption-desc-wrap.is-truncated .pswp-sm-caption-toggle) {
		display: block;
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
	}
	@media (min-width: 768px) {
		:global(.pswp-space-map .pswp-sm-caption-credits) {
			align-self: flex-end;
			margin-inline-start: auto;
			max-width: 50%;
			width: auto;
			padding: 0.25rem 0.5rem;
			background: rgba(0, 0, 0, 0.4);
			backdrop-filter: blur(4px);
			-webkit-backdrop-filter: blur(4px);
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
