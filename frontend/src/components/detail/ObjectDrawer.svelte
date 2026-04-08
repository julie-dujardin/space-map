<script lang="ts">
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import XIcon from '@lucide/svelte/icons/x';
	import type { PositionedBody } from '$lib/types/objects';
	import { fetchObjectDetail, type ObjectDetailData } from '$lib/fetch/objects/object-data';
	import ObjectHeader from './ObjectHeader.svelte';
	import ObjectDescription from './ObjectDescription.svelte';
	import Physical from './properties/Physical.svelte';
	import Orbital from './properties/Orbital.svelte';
	import Discovery from './properties/Discovery.svelte';
	import Mission from './properties/Mission.svelte';
	import ObjectLinks from './ObjectLinks.svelte';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		body: PositionedBody;
		onClose: () => void;
		onSheetResize?: (heightDvh: number) => void;
	}

	let { body, onClose, onSheetResize }: Props = $props();

	let data = $state<ObjectDetailData | null>(null);
	let loading = $state(true);
	let isMobile = $state(false);

	// Mobile bottom sheet snap points
	// Bottom snap is measured from the handle in px; mid/top are in dvh.
	let handleEl = $state<HTMLDivElement>();
	let bottomSnapPx = $state(0);
	const MID_SNAP = 30;
	const TOP_SNAP = 95;
	let sheetHeight = $state(0);
	let isDragging = $state(false);
	let dragStartY = 0;
	let dragStartHeight = 0;

	function bottomSnapDvh() {
		return (bottomSnapPx / window.innerHeight) * 100;
	}
	// Snaps always reflects current viewport
	function getSnaps(): [number, number, number] {
		return [bottomSnapDvh(), MID_SNAP, TOP_SNAP];
	}

	$effect(() => {
		if (!handleEl) return;
		const update = () => {
			bottomSnapPx = handleEl!.offsetHeight;
			if (sheetHeight < bottomSnapDvh()) sheetHeight = bottomSnapDvh();
		};
		update();
		const ro = new ResizeObserver(update);
		ro.observe(handleEl);
		return () => ro.disconnect();
	});

	// Velocity tracking (dvh/ms, positive = sheet moving up)
	let velocity = 0;
	let lastMoveY = 0;
	let lastMoveTime = 0;

	// Overscroll-to-collapse when fullscreen
	let contentEl = $state<HTMLDivElement>();
	let overscrolling = $state(false);
	let overscrollStartY = 0;

	$effect(() => {
		const mq = window.matchMedia('(max-width: 768px)');
		isMobile = mq.matches;
		const handler = (e: MediaQueryListEvent) => (isMobile = e.matches);
		mq.addEventListener('change', handler);
		return () => mq.removeEventListener('change', handler);
	});

	$effect(() => {
		void body.data.id;
		if (isMobile) sheetHeight = bottomSnapDvh();
	});

	$effect(() => {
		const id = body.data.id;
		loading = true;
		data = null;
		fetchObjectDetail(id, body.data.objectFileFlag)
			.then((result) => {
				if (body.data.id === id) {
					data = result;
					loading = false;
				}
			})
			.catch((err) => {
				loading = false;
				throw err;
			});
	});

	// Fast flick skips the middle snap; slow drag uses nearest
	const VELOCITY_THRESHOLD = 0.2; // dvh/ms

	function snap() {
		const s = getSnaps();
		if (velocity > VELOCITY_THRESHOLD) sheetHeight = s[2];
		else if (velocity < -VELOCITY_THRESHOLD) sheetHeight = s[0];
		else
			sheetHeight = s.reduce((a, b) =>
				Math.abs(a - sheetHeight) <= Math.abs(b - sheetHeight) ? a : b
			);
	}

	function trackVelocity(clientY: number, sign: 1 | -1) {
		const now = performance.now();
		const dt = now - lastMoveTime;
		if (dt > 0 && dt < 100) {
			// sign: +1 when upward pointer drag, -1 when downward touch overscroll
			velocity = (((sign * (lastMoveY - clientY)) / window.innerHeight) * 100) / dt;
		}
		lastMoveY = clientY;
		lastMoveTime = now;
	}

	// Drag: handle always; whole sheet when not fullscreen
	function onDragStart(e: PointerEvent) {
		isDragging = true;
		dragStartY = e.clientY;
		dragStartHeight = sheetHeight;
		velocity = 0;
		lastMoveY = e.clientY;
		lastMoveTime = performance.now();
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
	}

	function onHandlePointerDown(e: PointerEvent) {
		e.stopPropagation(); // prevent aside from also starting drag
		onDragStart(e);
	}

	function onAsidePointerDown(e: PointerEvent) {
		if (isFullscreen) return;
		onDragStart(e);
	}

	function onDragMove(e: PointerEvent) {
		if (!isDragging) return;
		trackVelocity(e.clientY, 1);
		const dy = ((dragStartY - e.clientY) / window.innerHeight) * 100;
		const s = getSnaps();
		sheetHeight = Math.max(s[0], Math.min(s[2], dragStartHeight + dy));
	}

	function onDragUp() {
		if (!isDragging) return;
		isDragging = false;
		snap();
	}

	// Overscroll-to-collapse: needs non-passive listener to call preventDefault
	function nonPassiveTouchMove(node: HTMLElement, handler: (e: TouchEvent) => void) {
		node.addEventListener('touchmove', handler, { passive: false });
		return { destroy: () => node.removeEventListener('touchmove', handler) };
	}

	let overscrollPeakVelocity = 0;

	function onContentTouchStart(e: TouchEvent) {
		overscrollStartY = e.touches[0].clientY;
		overscrolling = false;
		overscrollPeakVelocity = 0;
		lastMoveY = e.touches[0].clientY;
		lastMoveTime = performance.now();
	}

	function onContentTouchMove(e: TouchEvent) {
		if (!contentEl || (!isFullscreen && !overscrolling)) return;
		const dy = e.touches[0].clientY - overscrollStartY;
		if ((contentEl.scrollTop <= 0 && dy > 0) || overscrolling) {
			e.preventDefault();
			overscrolling = true;
			// Track peak velocity (finger moving down = collapsing = negative sign)
			const now = performance.now();
			const dt = now - lastMoveTime;
			if (dt > 0 && dt < 100) {
				const v = (((e.touches[0].clientY - lastMoveY) / window.innerHeight) * 100) / dt;
				if (v > overscrollPeakVelocity) overscrollPeakVelocity = v;
			}
			lastMoveY = e.touches[0].clientY;
			lastMoveTime = now;
			const dvh = (dy / window.innerHeight) * 100;
			sheetHeight = Math.max(bottomSnapDvh(), TOP_SNAP - dvh);
		}
	}

	function onContentTouchEnd() {
		if (overscrolling) {
			overscrolling = false;
			if (overscrollPeakVelocity > VELOCITY_THRESHOLD) sheetHeight = bottomSnapDvh();
			else snap();
		}
	}

	$effect(() => {
		if (isMobile) onSheetResize?.(sheetHeight);
	});

	let isAtBottomSnap = $derived(bottomSnapPx > 0 && sheetHeight <= bottomSnapDvh() + 1);
	let isExpanded = $derived(sheetHeight > bottomSnapDvh() + 5);
	let isFullscreen = $derived(sheetHeight >= TOP_SNAP - 5);

	let displayName = $derived(
		data?.localized?.name ?? data?.global?.name ?? body.data.name ?? m.loading()
	);
</script>

{#snippet drawerContent()}
	{#if loading}
		<div class="flex flex-col gap-4 p-1">
			<Skeleton class="w-full h-36 rounded-md" />
			<Skeleton class="w-3/4 h-6" />
			<Skeleton class="w-1/2 h-4" />
			<Skeleton class="w-full h-20" />
			<Skeleton class="w-full h-32" />
		</div>
	{:else}
		<div class="flex flex-col gap-5 p-1">
			<ObjectHeader
				global={data?.global ?? null}
				localized={data?.localized ?? null}
				fallbackName={body.data.name}
			/>
			<ObjectDescription extract={data?.localized?.wikipedia?.extract} />
			<Physical global={data?.global ?? null} />
			<Orbital global={data?.global ?? null} orbitElements={body.orbitElements} />
			<Discovery global={data?.global ?? null} localized={data?.localized ?? null} />
			<Mission global={data?.global ?? null} localized={data?.localized ?? null} />
			<ObjectLinks global={data?.global ?? null} localized={data?.localized ?? null} />
		</div>
	{/if}
{/snippet}

{#if isMobile}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<aside
		class="fixed inset-x-0 bottom-0 z-50 flex flex-col rounded-t-xl border-t bg-background shadow-lg {!isFullscreen
			? 'cursor-grab touch-none'
			: ''}"
		style="height: {isAtBottomSnap
			? `${bottomSnapPx}px`
			: `${sheetHeight}dvh`}; transition: {isDragging || overscrolling
			? 'none'
			: 'height 0.3s ease'};"
		onpointerdown={onAsidePointerDown}
		onpointermove={onDragMove}
		onpointerup={onDragUp}
		onpointercancel={onDragUp}
	>
		<!-- Drag handle (always draggable) -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			bind:this={handleEl}
			class="flex flex-col items-center gap-2 px-4 pt-3 pb-2 cursor-grab touch-none"
			onpointerdown={onHandlePointerDown}
			onpointermove={onDragMove}
			onpointerup={onDragUp}
			onpointercancel={onDragUp}
		>
			<div class="h-1 w-10 rounded-full bg-muted-foreground/40"></div>
			<div class="flex w-full items-center justify-between">
				<span class="text-sm font-semibold truncate">{displayName}</span>
				<Button variant="ghost" size="icon-sm" onclick={onClose}>
					<XIcon />
					<span class="sr-only">{m.close()}</span>
				</Button>
			</div>
		</div>

		{#if isExpanded}
			<div
				bind:this={contentEl}
				class="flex-1 px-4 pb-4 {isFullscreen ? 'overflow-y-auto' : 'overflow-hidden'}"
				ontouchstart={onContentTouchStart}
				ontouchend={onContentTouchEnd}
				use:nonPassiveTouchMove={onContentTouchMove}
			>
				{@render drawerContent()}
			</div>
		{/if}
	</aside>
{:else}
	<!-- Desktop: side panel -->
	<aside
		class="fixed top-0 left-0 z-50 flex h-full w-[380px] max-w-[90vw] flex-col border-r bg-background shadow-lg"
	>
		<div class="flex items-center justify-between p-2 px-4">
			<span class="text-sm font-semibold truncate">{displayName}</span>
			<Button variant="ghost" size="icon-sm" onclick={onClose}>
				<XIcon />
				<span class="sr-only">{m.close()}</span>
			</Button>
		</div>

		<ScrollArea class="flex-1 min-h-0">
			<div class="px-4 pb-4 -mt-2">
				{@render drawerContent()}
			</div>
		</ScrollArea>
	</aside>
{/if}
