<script lang="ts">
	// The drawer's mobile Vaul frame + snap machinery. `activeSnapPoint` stays
	// bindable in the drawer so the sheet height survives a mobile↔desktop
	// flip, which unmounts this component — the resize re-pin lives there too,
	// so a height change during a desktop interlude still repairs it.
	import { Drawer as Vaul } from 'vaul-svelte';
	import * as Tabs from '$lib/components/ui/tabs/index.js';
	import { DRAWER_TOP_GAP_PX, topSnapPx, trackSheetCover } from '$lib/drawer';
	import { getContext, type Snippet } from 'svelte';
	import type { MapCover } from '$lib/state/map-cover.svelte';

	interface Props {
		inert: boolean;
		activeSnapPoint: number | string | null;
		onSheetResize?: (heightDvh: number) => void;
		tab: string;
		onTabChange: (tab: string) => void;
		/** A promoted tab owns the whole sheet: its panel is no longer a
		 *  tabpanel, so there is no tab context to render it in. */
		solo?: boolean;
		/** Title row content; the sheet supplies the handle and measures the header. */
		header: Snippet;
		/** Scrollable content region (hero + tab bar + panels). */
		children: Snippet;
	}

	let {
		inert,
		activeSnapPoint = $bindable(),
		onSheetResize,
		tab,
		onTabChange,
		solo = false,
		header,
		children
	}: Props = $props();

	// Snap points: chrome-only collapsed (measured at runtime so it tracks the
	// real header height — buttons, fonts, locale length all affect it), mid,
	// full.
	const MID_SNAP = 0.3;

	let innerH = $state(typeof window === 'undefined' ? 800 : window.innerHeight);
	$effect(() => {
		const update = () => (innerH = window.innerHeight);
		window.addEventListener('resize', update);
		return () => window.removeEventListener('resize', update);
	});

	let headerEl = $state<HTMLDivElement | null>(null);
	// Initial guess close to the rendered size (icon-lg row + handle + paddings)
	// so the drawer opens at a sensible height before the first measurement.
	let headerHeightPx = $state(68);
	let collapsedSnap = $derived(`${headerHeightPx}px`);
	let topSnap = $derived(topSnapPx(innerH));
	let snapPoints = $derived([collapsedSnap, MID_SNAP, topSnap]);
	let isAtTop = $derived(activeSnapPoint === topSnap);

	let covers = $state(false);
	const cover = trackSheetCover((c) => (covers = c));
	$effect(() => cover.setAtTop(isAtTop));
	$effect(() => () => cover.dispose());
	getContext<MapCover>('mapCover').hold(() => covers);

	$effect(() => {
		const el = headerEl;
		if (!el) return;
		const measure = () => {
			const h = Math.ceil(el.getBoundingClientRect().height);
			if (h === headerHeightPx) return;
			// If the user is parked on the collapsed snap, follow the new height
			// so vaul doesn't end up with a stale activeSnapPoint that no longer
			// matches any entry in snapPoints.
			const wasCollapsed = activeSnapPoint === collapsedSnap;
			headerHeightPx = h;
			if (wasCollapsed) activeSnapPoint = `${h}px`;
		};
		measure();
		const ro = new ResizeObserver(measure);
		ro.observe(el);
		return () => ro.disconnect();
	});

	// Report the snap target on change, not during drag/animation — a per-frame
	// getBoundingClientRect loop caused layout thrash. Parent CSS-transitions `bottom`.
	$effect(() => {
		const s = activeSnapPoint;
		let dvh = 0;
		if (typeof s === 'number') {
			dvh = s * 100;
		} else if (typeof s === 'string') {
			const px = parseFloat(s);
			if (!Number.isNaN(px)) dvh = (px / window.innerHeight) * 100;
		}
		onSheetResize?.(dvh);
	});
</script>

{#snippet scroller()}
	<div
		class="flex-1 min-h-0 {isAtTop ? 'overflow-y-auto' : 'overflow-hidden'}"
		style="padding-bottom: calc(1rem + {DRAWER_TOP_GAP_PX}px + var(--safe-bottom));"
	>
		{@render children()}
	</div>
{/snippet}

<Vaul.Root
	open={true}
	{snapPoints}
	bind:activeSnapPoint
	shouldScaleBackground={false}
	dismissible={false}
	repositionInputs={false}
	onDrag={cover.onDrag}
	onRelease={cover.onRelease}
>
	<Vaul.Portal>
		<Vaul.Content
			{inert}
			trapFocus={false}
			aria-labelledby="detail-drawer-title"
			class="fixed inset-x-0 bottom-0 z-50 flex h-dvh max-h-dvh flex-col rounded-t-xl border-t bg-background shadow-lg outline-none"
		>
			<div bind:this={headerEl} class="flex flex-col items-center gap-2 px-4 pt-3 pb-2">
				<div class="h-1 w-10 rounded-full bg-muted-foreground/40"></div>
				<div class="flex w-full items-center justify-between gap-2">
					{@render header()}
				</div>
			</div>
			{#if solo}
				{@render scroller()}
			{:else}
				<Tabs.Root value={tab} onValueChange={onTabChange} class="flex flex-1 min-h-0 flex-col">
					{@render scroller()}
				</Tabs.Root>
			{/if}
		</Vaul.Content>
	</Vaul.Portal>
</Vaul.Root>
