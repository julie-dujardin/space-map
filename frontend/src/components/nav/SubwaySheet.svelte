<!--
  The Δv map's controls on a phone: a sheet over the foot of the page, the way
  the map's drawer is. Collapsed it shows the handle and the fields in `head`;
  dragged up it shows the rest, which scrolls only once the sheet is at its top.
-->
<script lang="ts">
	import { Drawer as Vaul } from 'vaul-svelte';
	import type { Snippet } from 'svelte';
	import { topSnapPx } from '$lib/drawer';

	interface Props {
		/** Names the sheet. */
		label: string;
		/** What stays in view while the sheet is collapsed. */
		head: Snippet;
		children: Snippet;
		/** The collapsed height, so the page can keep clear of it. */
		collapsedPx?: number;
	}

	let { label, head, children, collapsedPx = $bindable(132) }: Props = $props();

	const MID_SNAP = 0.55;

	let innerH = $state(typeof window === 'undefined' ? 800 : window.innerHeight);
	let headEl = $state<HTMLDivElement | null>(null);
	const collapsedSnap = $derived(`${collapsedPx}px`);
	const topSnap = $derived(topSnapPx(innerH));
	const snapPoints = $derived([collapsedSnap, MID_SNAP, topSnap]);
	let activeSnapPoint = $state<number | string | null>(`${collapsedPx}px`);
	const isAtTop = $derived(activeSnapPoint === topSnap);

	// A snap parked on a pixel height has to follow that height, or vaul is
	// left holding one that is no longer in its list.
	$effect(() => {
		const update = () => {
			const wasTop = activeSnapPoint === topSnapPx(innerH);
			innerH = window.innerHeight;
			if (wasTop) activeSnapPoint = topSnapPx(innerH);
		};
		window.addEventListener('resize', update);
		return () => window.removeEventListener('resize', update);
	});

	$effect(() => {
		const el = headEl;
		if (!el) return;
		const measure = () => {
			const h = Math.ceil(el.getBoundingClientRect().height);
			if (h === collapsedPx) return;
			const wasCollapsed = activeSnapPoint === `${collapsedPx}px`;
			collapsedPx = h;
			if (wasCollapsed) activeSnapPoint = `${h}px`;
		};
		measure();
		const ro = new ResizeObserver(measure);
		ro.observe(el);
		return () => ro.disconnect();
	});
</script>

<!-- Non-modal: the map stays scrollable and its stops stay links under it. -->
<Vaul.Root
	open={true}
	modal={false}
	{snapPoints}
	bind:activeSnapPoint
	shouldScaleBackground={false}
	dismissible={false}
	repositionInputs={false}
>
	<Vaul.Portal>
		<Vaul.Content
			trapFocus={false}
			aria-label={label}
			class="fixed inset-x-0 bottom-0 z-40 flex h-dvh max-h-dvh flex-col rounded-t-2xl border-t border-border bg-background shadow-[0_-10px_30px_rgb(0_0_0/0.12)] outline-none"
		>
			<div
				bind:this={headEl}
				class="flex shrink-0 flex-col gap-3 px-6 pt-2 pb-[calc(0.75rem+var(--safe-bottom))]"
			>
				<div class="h-1 w-9 self-center rounded-full bg-muted-foreground/40"></div>
				{@render head()}
			</div>
			<div
				class="min-h-0 flex-1 px-6 pb-[calc(2rem+var(--safe-bottom))] {isAtTop
					? 'overflow-y-auto'
					: 'overflow-hidden'}"
			>
				{@render children()}
			</div>
		</Vaul.Content>
	</Vaul.Portal>
</Vaul.Root>
