<script lang="ts">
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import XIcon from '@lucide/svelte/icons/x';
	import type { PositionedBody } from '$lib/types';
	import { fetchObjectDetail, type ObjectDetailData } from '$lib/object-data';
	import ObjectHeader from './ObjectHeader.svelte';
	import ObjectDescription from './ObjectDescription.svelte';
	import ObjectProperties from './ObjectProperties.svelte';
	import ObjectDiscovery from './ObjectDiscovery.svelte';
	import ObjectLinks from './ObjectLinks.svelte';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		body: PositionedBody;
		onClose: () => void;
	}

	let { body, onClose }: Props = $props();

	let data = $state<ObjectDetailData | null>(null);
	let loading = $state(true);
	let isMobile = $state(false);

	// Mobile bottom sheet snap points (% of dynamic viewport height)
	const SNAP_COLLAPSED = 12;
	const SNAP_HALF = 50;
	const SNAP_FULL = 95;
	let sheetHeight = $state(SNAP_COLLAPSED);
	let dragging = $state(false);
	let dragStartY = 0;
	let dragStartHeight = 0;

	$effect(() => {
		const mq = window.matchMedia('(max-width: 768px)');
		isMobile = mq.matches;
		const handler = (e: MediaQueryListEvent) => (isMobile = e.matches);
		mq.addEventListener('change', handler);
		return () => mq.removeEventListener('change', handler);
	});

	// Reset to collapsed when body changes on mobile
	$effect(() => {
		const _track = body.data.fileId;
		void _track;
		if (isMobile) sheetHeight = SNAP_COLLAPSED;
	});

	$effect(() => {
		const fileId = body.data.fileId;
		if (!fileId) return;
		loading = true;
		data = null;
		fetchObjectDetail(fileId).then((result) => {
			if (body.data.fileId === fileId) {
				data = result;
				loading = false;
			}
		});
	});

	function onDragStart(e: PointerEvent) {
		dragging = true;
		dragStartY = e.clientY;
		dragStartHeight = sheetHeight;
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
	}

	function onDragMove(e: PointerEvent) {
		if (!dragging) return;
		const dy = dragStartY - e.clientY;
		const dvh = (dy / window.innerHeight) * 100;
		sheetHeight = Math.max(SNAP_COLLAPSED, Math.min(SNAP_FULL, dragStartHeight + dvh));
	}

	function snapTo(height: number, direction: number) {
		const snaps = [SNAP_COLLAPSED, SNAP_HALF, SNAP_FULL];
		// Find the two nearest snap points (below and above)
		let below = snaps[0];
		let above = snaps[snaps.length - 1];
		for (const s of snaps) {
			if (s <= height) below = s;
			if (s >= height && above === snaps[snaps.length - 1]) above = s;
		}
		if (below === above) return below;
		// Snap in the direction of movement; if ambiguous, pick nearest
		if (direction > 0) return above;
		if (direction < 0) return below;
		return height - below < above - height ? below : above;
	}

	function onDragEnd() {
		if (!dragging) return;
		const direction = sheetHeight - dragStartHeight; // positive = dragged up
		dragging = false;
		sheetHeight = snapTo(sheetHeight, direction);
	}

	// When fully expanded and scrolled to top, pulling down should collapse the sheet
	let contentEl: HTMLDivElement | undefined = $state();
	let pullDownActive = $state(false);
	let pullDownStartY = 0;

	function onContentTouchStart(e: TouchEvent) {
		if (contentEl && contentEl.scrollTop <= 0) {
			pullDownStartY = e.touches[0].clientY;
			pullDownActive = false;
		}
	}

	function onContentTouchMove(e: TouchEvent) {
		if (!contentEl) return;
		// If already scrolled into content, let native scroll handle it
		if (contentEl.scrollTop > 0 && !pullDownActive) {
			return;
		}
		const dy = e.touches[0].clientY - pullDownStartY;
		if (dy > 0) {
			// Pulling down from top — take over
			e.preventDefault();
			pullDownActive = true;
			const dvh = (dy / window.innerHeight) * 100;
			sheetHeight = Math.max(SNAP_COLLAPSED, Math.min(SNAP_FULL, SNAP_FULL - dvh));
		}
	}

	function onContentTouchEnd() {
		if (pullDownActive) {
			pullDownActive = false;
			sheetHeight = snapTo(sheetHeight, -1); // always pulling down
		}
	}

	let isExpanded = $derived(sheetHeight > SNAP_COLLAPSED + 5);
	let canScroll = $derived(sheetHeight >= SNAP_FULL - 5);
</script>

{#if isMobile}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<aside
		class="fixed inset-x-0 bottom-0 z-50 flex flex-col rounded-t-xl border-t bg-background shadow-lg {canScroll
			? ''
			: 'cursor-grab touch-none'}"
		style="height: {sheetHeight}dvh; transition: {dragging || pullDownActive
			? 'none'
			: 'height 0.3s ease'};"
		onpointerdown={canScroll ? undefined : onDragStart}
		onpointermove={canScroll ? undefined : onDragMove}
		onpointerup={canScroll ? undefined : onDragEnd}
		onpointercancel={canScroll ? undefined : onDragEnd}
	>
		<!-- Drag handle -->
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="flex flex-col items-center gap-2 px-4 pt-3 pb-2 cursor-grab touch-none"
			onpointerdown={onDragStart}
			onpointermove={onDragMove}
			onpointerup={onDragEnd}
			onpointercancel={onDragEnd}
		>
			<div class="h-1 w-10 rounded-full bg-muted-foreground/40"></div>
			{#if !isExpanded}
				<div class="flex w-full items-center justify-between">
					<span class="text-sm font-semibold truncate">
						{data?.localized?.name ?? data?.global?.name ?? body.data.name ?? m.loading()}
					</span>
					<Button variant="ghost" size="icon-sm" onclick={onClose}>
						<XIcon />
						<span class="sr-only">{m.close()}</span>
					</Button>
				</div>
			{/if}
		</div>

		{#if isExpanded}
			<div
				bind:this={contentEl}
				class="flex-1 px-4 pb-4 {canScroll ? 'overflow-y-auto' : 'overflow-hidden'}"
				ontouchstart={canScroll ? onContentTouchStart : undefined}
				ontouchmove={canScroll ? onContentTouchMove : undefined}
				ontouchend={canScroll ? onContentTouchEnd : undefined}
			>
				<div class="flex justify-end -mt-1 mb-1">
					<Button variant="ghost" size="icon-sm" onclick={onClose}>
						<XIcon />
						<span class="sr-only">{m.close()}</span>
					</Button>
				</div>
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
						<ObjectProperties global={data?.global ?? null} />
						<ObjectDiscovery global={data?.global ?? null} localized={data?.localized ?? null} />
						<ObjectLinks global={data?.global ?? null} localized={data?.localized ?? null} />
					</div>
				{/if}
			</div>
		{/if}
	</aside>
{:else}
	<!-- Desktop: side panel -->
	<aside
		class="fixed top-0 left-0 z-50 flex h-full w-[380px] max-w-[90vw] flex-col border-r bg-background shadow-lg"
	>
		<div class="flex justify-end p-2">
			<Button variant="ghost" size="icon-sm" onclick={onClose}>
				<XIcon />
				<span class="sr-only">{m.close()}</span>
			</Button>
		</div>

		<ScrollArea class="flex-1 min-h-0">
			<div class="px-4 pb-4 -mt-2">
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
						<ObjectProperties global={data?.global ?? null} />
						<ObjectDiscovery global={data?.global ?? null} localized={data?.localized ?? null} />
						<ObjectLinks global={data?.global ?? null} localized={data?.localized ?? null} />
					</div>
				{/if}
			</div>
		</ScrollArea>
	</aside>
{/if}
