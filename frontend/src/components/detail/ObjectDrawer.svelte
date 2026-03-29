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
	const SNAPS = [12, 50, 95];
	let sheetHeight = $state(SNAPS[0]);
	let isDragging = $state(false);
	let dragStartY = 0;
	let dragStartHeight = 0;

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
		void body.data.fileId;
		if (isMobile) sheetHeight = SNAPS[0];
	});

	$effect(() => {
		const fileId = body.data.fileId;
		if (!fileId) return;
		loading = true;
		data = null;
		fetchObjectDetail(fileId)
			.then((result) => {
				if (body.data.fileId === fileId) {
					data = result;
					loading = false;
				}
			})
			.catch((err) => {
				console.warn(`ObjectDrawer: failed to load detail for ${fileId}:`, err);
				if (body.data.fileId === fileId) loading = false;
			});
	});

	function snapToNearest() {
		sheetHeight = SNAPS.reduce((a, b) =>
			Math.abs(a - sheetHeight) <= Math.abs(b - sheetHeight) ? a : b
		);
	}

	// Drag: handle always; whole sheet when not fullscreen
	function onDragStart(e: PointerEvent) {
		isDragging = true;
		dragStartY = e.clientY;
		dragStartHeight = sheetHeight;
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
		const dy = ((dragStartY - e.clientY) / window.innerHeight) * 100;
		sheetHeight = Math.max(SNAPS[0], Math.min(SNAPS[SNAPS.length - 1], dragStartHeight + dy));
	}

	function onDragUp() {
		if (!isDragging) return;
		isDragging = false;
		snapToNearest();
	}

	// Overscroll-to-collapse: needs non-passive listener to call preventDefault
	function nonPassiveTouchMove(node: HTMLElement, handler: (e: TouchEvent) => void) {
		node.addEventListener('touchmove', handler, { passive: false });
		return { destroy: () => node.removeEventListener('touchmove', handler) };
	}

	function onContentTouchStart(e: TouchEvent) {
		overscrollStartY = e.touches[0].clientY;
		overscrolling = false;
	}

	function onContentTouchMove(e: TouchEvent) {
		if (!contentEl || (!isFullscreen && !overscrolling)) return;
		const dy = e.touches[0].clientY - overscrollStartY;
		if ((contentEl.scrollTop <= 0 && dy > 0) || overscrolling) {
			e.preventDefault();
			overscrolling = true;
			const dvh = (dy / window.innerHeight) * 100;
			sheetHeight = Math.max(SNAPS[0], SNAPS[SNAPS.length - 1] - dvh);
		}
	}

	function onContentTouchEnd() {
		if (overscrolling) {
			overscrolling = false;
			snapToNearest();
		}
	}

	let isExpanded = $derived(sheetHeight > SNAPS[0] + 5);
	let isFullscreen = $derived(sheetHeight >= SNAPS[SNAPS.length - 1] - 5);

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
			<ObjectProperties global={data?.global ?? null} />
			<ObjectDiscovery global={data?.global ?? null} localized={data?.localized ?? null} />
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
		style="height: {sheetHeight}dvh; transition: {isDragging || overscrolling
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
