<script lang="ts">
	import { getContext } from 'svelte';
	import { Drawer as Vaul } from 'vaul-svelte';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import XIcon from '@lucide/svelte/icons/x';
	import { MaximizeIcon, MinimizeIcon } from '@lucide/svelte';
	import type { PositionedBody } from '$lib/types/objects';
	import type { ContextManager } from '$lib/scene/context-manager.svelte';
	import type { SimClock } from '$lib/scene/clock.svelte';
	import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
	import { fetchObjectDetail, type ObjectDetailData } from '$lib/fetch/objects/object-data';
	import type { AppState } from '$lib/state/app-state.svelte';
	import ObjectHeader from './ObjectHeader.svelte';
	import ImageViewer from '../ImageViewer.svelte';
	import ObjectDescription from './ObjectDescription.svelte';
	import Physical from './properties/Physical.svelte';
	import Orbital from './properties/Orbital.svelte';
	import Discovery from './properties/Discovery.svelte';
	import Mission from './properties/Mission.svelte';
	import ObjectLinks from './ObjectLinks.svelte';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		body: PositionedBody;
		clock: SimClock;
		onClose: () => void;
		onMaximize: () => void;
		onMinimize: () => void;
		onSheetResize?: (heightDvh: number) => void;
	}

	let { body, clock, onClose, onMaximize, onMinimize, onSheetResize }: Props = $props();

	const ctx = getContext<ContextManager>('ctx');
	const appState = getContext<AppState>('appState');
	let parentBody = $derived(ctx?.getBody(body.data.parentId));

	// Sample sim time at 2 Hz so speed/altitude in the description update
	// smoothly without re-deriving on every animation frame.
	let sampledJd = $state(clock.jd);
	$effect(() => {
		const id = setInterval(() => (sampledJd = clock.jd), 200);
		return () => clearInterval(id);
	});

	let data = $state<ObjectDetailData | null>(null);
	let loading = $state(true);
	let isMobile = $state(false);

	$effect(() => {
		const mq = window.matchMedia('(max-width: 768px)');
		isMobile = mq.matches;
		const handler = (e: MediaQueryListEvent) => (isMobile = e.matches);
		mq.addEventListener('change', handler);
		return () => mq.removeEventListener('change', handler);
	});

	$effect(() => {
		const id = body.data.id;
		loading = true;
		data = null;
		fetchObjectDetail(id, body.data.hasLocalized)
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

	// Snap points: handle-only collapsed, mid, full.
	const SNAP_POINTS = ['56px', 0.3, 0.95] as const;
	const TOP_SNAP = SNAP_POINTS[2];
	// The drawer is h-dvh (vaul assumes that). If the top snap is < 1 the bottom
	// (1 - TOP_SNAP) of the drawer stays below the viewport even when expanded,
	// so the scroll container needs that much extra bottom padding to let the
	// last content into view.
	const HIDDEN_BOTTOM_DVH = typeof TOP_SNAP === 'number' ? (1 - TOP_SNAP) * 100 : 0;
	let activeSnapPoint = $state<number | string | null>(SNAP_POINTS[0]);
	let isAtTop = $derived(activeSnapPoint === TOP_SNAP);

	// Report the snap target to the parent on change. We don't sample during
	// the drag/animation — a per-frame getBoundingClientRect loop caused layout
	// thrash that made snap transitions jank on mobile. The parent smooths the
	// discrete jumps with its own CSS transition on `bottom`.
	$effect(() => {
		if (!isMobile) return;
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

	let resolvedName = $derived(data?.localized?.name ?? data?.global?.name ?? body.data.name);
	let displayName = $derived(resolvedName ?? (loading ? m.loading() : body.data.id));

	// Once the detail bundle resolves, push the now-known name into the URL
	// (and via that, the page title). On permanent failure — bundle resolved
	// without any name — log once and fall back to the id, so the user sees
	// *something* identifiable instead of an empty drawer header.
	$effect(() => {
		if (loading) return;
		if (!resolvedName) {
			console.warn(
				`No name resolved for ${body.data.id} after detail fetch; using id as fallback.`
			);
		}
		appState.replaceFocusName(resolvedName ?? body.data.id);
	});
	// Flip to the minimize button well before the maximize target distance, so
	// that finishing a maximize fly-to lands the camera comfortably inside the
	// minimize zone (and floating-point/animation overshoot can't leave it
	// stuck on the maximize side of an exact threshold).
	let isMinimized = $derived(appState ? appState.view.zoom <= minCameraDistance(body) * 20 : false);
	let viewerImages = $derived(data?.global?.images);
	let viewerIndex = $derived(appState?.view.imageIndex);
	// Gate the viewer mount on a valid index AND a loaded images list. The
	// AppState's `?img=` URL parser doesn't know how many images this object
	// has, so we belt-and-braces the bound here too.
	let viewerActive = $derived(
		!!viewerImages &&
			viewerImages.length > 0 &&
			viewerIndex != null &&
			viewerIndex < viewerImages.length
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
			<ObjectDescription
				extract={data?.localized?.wikipedia?.extract}
				wikipediaUrl={data?.localized?.wikipedia?.url}
			/>
			<div class="grid grid-cols-[auto_1fr_auto] gap-y-5">
				<Physical global={data?.global ?? null} />
				<Orbital
					global={data?.global ?? null}
					localized={data?.localized ?? null}
					{body}
					orbitElements={body.orbitElements ?? body.data}
					{parentBody}
					jd={sampledJd}
				/>
				<Discovery global={data?.global ?? null} localized={data?.localized ?? null} />
				<Mission global={data?.global ?? null} localized={data?.localized ?? null} />
			</div>
			<ObjectLinks global={data?.global ?? null} localized={data?.localized ?? null} />
		</div>
	{/if}
{/snippet}

{#if isMobile}
	<Vaul.Root
		open={true}
		snapPoints={SNAP_POINTS as unknown as (number | string)[]}
		bind:activeSnapPoint
		shouldScaleBackground={false}
		dismissible={false}
	>
		<Vaul.Portal>
			<Vaul.Content
				class="fixed inset-x-0 bottom-0 z-50 flex h-dvh max-h-dvh flex-col rounded-t-xl border-t bg-background shadow-lg outline-none"
			>
				<div class="flex flex-col items-center gap-2 px-4 pt-3 pb-2">
					<div class="h-1 w-10 rounded-full bg-muted-foreground/40"></div>
					<div class="flex w-full items-center justify-between">
						<span class="text-sm font-semibold truncate">{displayName}</span>
						<div class="flex items-center gap-1">
							{#if isMinimized}
								<Button variant="ghost" size="icon-sm" onclick={onMinimize}>
									<MinimizeIcon />
									<span class="sr-only">{m.zoom_out_to_system()}</span>
								</Button>
							{:else}
								<Button variant="ghost" size="icon-sm" onclick={onMaximize}>
									<MaximizeIcon />
									<span class="sr-only">{m.go_to_object()}</span>
								</Button>
							{/if}
							<Button variant="ghost" size="icon-sm" onclick={onClose}>
								<XIcon />
								<span class="sr-only">{m.close()}</span>
							</Button>
						</div>
					</div>
				</div>
				<div
					class="flex-1 min-h-0 px-4 {isAtTop ? 'overflow-y-auto' : 'overflow-hidden'}"
					style="padding-bottom: calc(1rem + {HIDDEN_BOTTOM_DVH}dvh);"
				>
					{@render drawerContent()}
				</div>
			</Vaul.Content>
		</Vaul.Portal>
	</Vaul.Root>
{:else}
	<!-- Desktop: side panel -->
	<aside
		class="fixed top-0 start-0 z-50 flex h-full w-[380px] max-w-[90vw] flex-col border-e bg-background shadow-lg"
	>
		<div class="flex items-center justify-between p-2 px-4">
			<span class="text-sm font-semibold truncate">{displayName}</span>
			<div class="flex items-center gap-1">
				{#if isMinimized}
					<Button variant="ghost" size="icon-sm" onclick={onMinimize}>
						<MinimizeIcon />
						<span class="sr-only">{m.zoom_out_to_system()}</span>
					</Button>
				{:else}
					<Button variant="ghost" size="icon-sm" onclick={onMaximize}>
						<MaximizeIcon />
						<span class="sr-only">{m.go_to_object()}</span>
					</Button>
				{/if}
				<Button variant="ghost" size="icon-sm" onclick={onClose}>
					<XIcon />
					<span class="sr-only">{m.close()}</span>
				</Button>
			</div>
		</div>

		<ScrollArea class="flex-1 min-h-0">
			<div class="px-4 pb-4">
				{@render drawerContent()}
			</div>
		</ScrollArea>
	</aside>
{/if}

<!-- Mounted as a sibling of the drawer/aside, not a descendant: keeps the
     viewer's lifecycle and pointer events out of Vaul's drag detection and
     out of the drawer's CSS transform context. PhotoSwipe additionally
     appends its own DOM to document.body. -->
{#if viewerActive && viewerImages}
	<ImageViewer images={viewerImages} alt={displayName} />
{/if}
