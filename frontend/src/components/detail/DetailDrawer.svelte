<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import { Drawer as Vaul } from 'vaul-svelte';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { groupTypeLabel, satelliteCategoryLabel } from '$lib/format/group';
	import GroupStatCards from './properties/GroupStatCards.svelte';
	import * as Tabs from '$lib/components/ui/tabs/index.js';
	import XIcon from '@lucide/svelte/icons/x';
	import Share2Icon from '@lucide/svelte/icons/share-2';
	import { MaximizeIcon, MinimizeIcon } from '@lucide/svelte';
	import { toast } from 'svelte-sonner';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
	import { fetchObjectDetail, type ObjectDetailData } from '$lib/fetch/objects/object-data';
	import { fetchFeatureDetail, type FeatureDetailData } from '$lib/fetch/nomenclature/details';
	import { fetchGroupDetail, type GroupDetailData } from '$lib/fetch/groups/details';
	import type { AppState } from '$lib/state/app-state.svelte';
	import {
		type Focusable,
		focusableFallbackName,
		focusableKey,
		groupSlugLabel
	} from '$lib/state/focusable';
	import ObjectHeader from './ObjectHeader.svelte';
	import DrawerTitle from './DrawerTitle.svelte';
	import { parentCrumb } from '$lib/state/breadcrumb';
	import ImageViewer from '../image-viewer/ImageViewer.svelte';
	import ImageGallery from './ImageGallery.svelte';
	import ObjectDescription from './ObjectDescription.svelte';
	import Physical from './properties/Physical.svelte';
	import Orbital from './properties/Orbital.svelte';
	import Discovery from './properties/Discovery.svelte';
	import Mission from './properties/Mission.svelte';
	import GroupProperties from './properties/GroupProperties.svelte';
	import ChildGroups from './properties/ChildGroups.svelte';
	import FeatureProperties from './properties/FeatureProperties.svelte';
	import MemberStrip from './members/MemberStrip.svelte';
	import MemberList from './members/MemberList.svelte';
	import ObjectLinks from './ObjectLinks.svelte';
	import { formatCompactNumber } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';

	// Module-scope dedupe so the "no name resolved" warning fires at most once
	// per focusable across the session — survives drawer remounts and effect
	// re-runs.
	const nameMissingLogged = new Set<string>();

	interface Props {
		focusable: Focusable;
		clock: SimClock;
		onClose: () => void;
		onMaximize: () => void;
		onMinimize: () => void;
		onSheetResize?: (heightDvh: number) => void;
	}

	let { focusable, clock, onClose, onMaximize, onMinimize, onSheetResize }: Props = $props();

	let body = $derived(focusable.kind === 'group' ? null : focusable.body);
	let feature = $derived(focusable.kind === 'feature' ? focusable.feature : null);
	let isFeatureMode = $derived(focusable.kind === 'feature');
	let isGroupMode = $derived(focusable.kind === 'group');
	let groupHeaderBadges = $derived.by(() => {
		const g = groupDetail?.global;
		if (!g) return undefined;
		const out: string[] = [groupTypeLabel(g.type)];
		for (const c of g.categories ?? []) out.push(satelliteCategoryLabel(c));
		return out;
	});

	const ctx = getContext<ContextManager>('ctx');
	const appState = getContext<AppState>('appState');
	let parentBody = $derived(body ? ctx?.getBody(body.data.parentId) : undefined);

	// Probes carry a=e=i=…=0 in body.data (no osculating elements — their
	// positions come from per-sub-chunk dispatch). Feeding those zeros to the
	// Orbital panel triggers a per-frame non-finite-elements warning, so leave
	// orbitElements undefined for probes; the panel hides the affected rows.
	let drawerOrbitElements = $derived(
		body
			? (body.orbitElements ??
					(body.data.orbitalSource === OrbitalSource.SPICE_PROBE ? undefined : body.data))
			: undefined
	);

	// Sample sim time at 2 Hz so speed/altitude in the description update
	// smoothly without re-deriving on every animation frame.
	let sampledJd = $state(0);
	$effect(() => {
		sampledJd = clock.jd;
		const id = setInterval(() => (sampledJd = clock.jd), 200);
		return () => clearInterval(id);
	});

	let data = $state<ObjectDetailData | null>(null);
	let featureDetail = $state<FeatureDetailData | null>(null);
	let groupDetail = $state<GroupDetailData | null>(null);
	let loading = $state(true);
	// String key so the load effect ignores parent re-derivations that return a
	// new focusable ref with the same logical identity (replaceFocusName churn).
	let focusableId = $derived(focusableKey(focusable));
	let isMobile = $state(false);

	$effect(() => {
		const mq = window.matchMedia('(max-width: 768px)');
		isMobile = mq.matches;
		const handler = (e: MediaQueryListEvent) => (isMobile = e.matches);
		mq.addEventListener('change', handler);
		return () => mq.removeEventListener('change', handler);
	});

	$effect(() => {
		// Track only the stable key — focusable identity churns on every view
		// reassignment (camera/time/replaceFocusName) and would re-fetch.
		const key = focusableId;
		const current = untrack(() => focusable);
		loading = true;
		data = null;
		featureDetail = null;
		groupDetail = null;
		if (current.kind === 'feature') {
			const f = current.feature;
			const bodyId = current.body.data.id;
			fetchFeatureDetail(bodyId, f.featureId)
				.then((detail) => {
					if (focusableId !== key) return;
					featureDetail = detail;
					data = {
						global: {
							id: `feature-${f.featureId}`,
							type: 'feature',
							name: f.name,
							images: detail.global?.images,
							cross_refs: detail.global?.wikidata_qid
								? { wikidata_qid: detail.global.wikidata_qid }
								: undefined
						},
						localized: detail.localized
							? {
									description: detail.localized.description,
									aliases: detail.localized.aliases,
									instance_of: detail.localized.instance_of,
									named_after: detail.localized.named_after,
									wikipedia: detail.localized.wikipedia
								}
							: null
					};
					loading = false;
				})
				.catch((err) => {
					loading = false;
					throw err;
				});
			return;
		}
		if (current.kind === 'group') {
			const slug = current.slug;
			fetchGroupDetail(slug)
				.then((detail) => {
					if (focusableId !== key) return;
					groupDetail = detail;
					const websites = [detail.global?.website, detail.global?.url].filter(
						(u): u is string => !!u
					);
					data = {
						global: {
							id: `group-${slug}`,
							type: 'group',
							name: detail.localized?.name ?? groupSlugLabel(slug),
							images: detail.global?.images,
							cross_refs: detail.global?.wikidata_qid
								? { wikidata_qid: detail.global.wikidata_qid }
								: undefined,
							wikidata: websites.length > 0 ? { website: websites } : undefined
						},
						localized: detail.localized
							? {
									name: detail.localized.name,
									description: detail.localized.description,
									wikipedia: detail.localized.wikipedia
								}
							: null
					};
					loading = false;
				})
				.catch((err) => {
					loading = false;
					throw err;
				});
			return;
		}
		const bodyId = current.body.data.id;
		const hasLocalized = current.body.data.hasLocalized;
		fetchObjectDetail(bodyId, hasLocalized)
			.then((result) => {
				if (focusableId === key) {
					data = result;
					loading = false;
				}
			})
			.catch((err) => {
				loading = false;
				throw err;
			});
	});

	// Snap points: chrome-only collapsed (measured at runtime so it tracks the
	// real header height — buttons, fonts, locale length all affect it), mid,
	// full.
	const TOP_SNAP = 0.95;
	const MID_SNAP = 0.3;
	// The drawer is h-dvh. If the top snap is < 1 the bottom (1 - TOP_SNAP)
	// of the drawer stays below the viewport even when expanded, so the
	// scroll container needs that much extra bottom padding to let the last
	// content into view.
	const HIDDEN_BOTTOM_DVH = (1 - TOP_SNAP) * 100;

	let headerEl = $state<HTMLDivElement | null>(null);
	// Initial guess close to the rendered size (icon-lg row + handle + paddings)
	// so the drawer opens at a sensible height before the first measurement.
	let headerHeightPx = $state(68);
	let collapsedSnap = $derived(`${headerHeightPx}px`);
	let snapPoints = $derived([collapsedSnap, MID_SNAP, TOP_SNAP]);
	let activeSnapPoint = $state<number | string | null>('68px');
	let isAtTop = $derived(activeSnapPoint === TOP_SNAP);

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

	let crumb = $derived(parentCrumb(focusable, ctx, data, groupDetail?.global ?? null));
	let fallbackName = $derived(focusableFallbackName(focusable));
	let resolvedName = $derived(data?.localized?.name ?? data?.global?.name ?? fallbackName);
	let displayName = $derived(resolvedName ?? (loading ? m.loading() : focusableKey(focusable)));

	// Once the detail bundle resolves, push the now-known name into the URL
	// (and via that, the page title). On permanent failure — bundle resolved
	// without any name — log once per focusable and fall back to its key, so
	// the user sees *something* identifiable instead of an empty drawer header
	// (and the console isn't spammed by repeated effect re-runs).
	$effect(() => {
		if (loading) return;
		// Stable key — avoids re-firing (and ping-ponging via replaceFocusName) on view churn.
		const key = focusableId;
		if (!resolvedName && !nameMissingLogged.has(key)) {
			nameMissingLogged.add(key);
			console.warn(`No name resolved for ${key} after detail fetch; using id as fallback.`);
		}
		appState.replaceFocusName(resolvedName ?? key);
	});
	// Flip to the minimize button well before the maximize target distance, so
	// that finishing a maximize fly-to lands the camera comfortably inside the
	// minimize zone (and floating-point/animation overshoot can't leave it
	// stuck on the maximize side of an exact threshold).
	let isMinimized = $derived(
		appState && body ? appState.view.zoom <= minCameraDistance(body) * 20 : false
	);
	let showCameraButtons = $derived(!isFeatureMode && !isGroupMode);
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

	async function handleShare() {
		const url = window.location.href;
		if (navigator.share) {
			try {
				await navigator.share({ url, title: displayName });
				return;
			} catch (err) {
				// User dismissed the native share sheet — nothing to do.
				if ((err as DOMException).name === 'AbortError') return;
				// Other failures fall through to the clipboard fallback below.
			}
		}
		try {
			await navigator.clipboard.writeText(url);
			toast.success(m.link_copied());
		} catch (err) {
			console.warn('Share failed:', err);
		}
	}

	let hasImages = $derived(!!viewerImages && viewerImages.length > 0);
	// The members tab is shared: groups list notable members, bodies list moons.
	let notableMembers = $derived(
		isGroupMode ? groupDetail?.global?.notable_members : data?.global?.notable_moons
	);
	let memberNames = $derived(
		isGroupMode ? groupDetail?.localized?.notable_member_names : data?.localized?.notable_moon_names
	);
	let memberTotal = $derived(
		isGroupMode ? (groupDetail?.global?.member_count ?? 0) : (data?.global?.moon_count ?? 0)
	);
	let membersHeading = $derived(isGroupMode ? m.members_notable() : m.moons_section());
	let membersTabLabel = $derived(isGroupMode ? m.tab_members() : m.tab_moons());
	let hasMembers = $derived(!!notableMembers && notableMembers.length > 0);
	let activeTab = $state<'overview' | 'images' | 'members'>('overview');
	// Switching to a focusable that lacks the active tab's content would
	// leave the panel empty — fall back to overview.
	$effect(() => {
		if (!hasImages && activeTab === 'images') activeTab = 'overview';
		if (!hasMembers && activeTab === 'members') activeTab = 'overview';
	});
</script>

{#snippet tabsBar()}
	<div class="border-b -mx-1 px-1">
		<Tabs.List variant="line" class="h-9 gap-2 -mb-px">
			<Tabs.Trigger value="overview" class="px-2">{m.tab_overview()}</Tabs.Trigger>
			{#if hasImages}
				<Tabs.Trigger value="images" class="px-2">
					{m.tab_images()}
					<Badge variant="secondary" class="text-[10px] py-0 px-1.5 h-4 leading-none">
						{viewerImages?.length}
					</Badge>
				</Tabs.Trigger>
			{/if}
			{#if hasMembers}
				<Tabs.Trigger value="members" class="px-2">
					{membersTabLabel}
					<Badge variant="secondary" class="text-[10px] py-0 px-1.5 h-4 leading-none">
						{formatCompactNumber(memberTotal)}
					</Badge>
				</Tabs.Trigger>
			{/if}
		</Tabs.List>
	</div>
{/snippet}

{#snippet overviewPanel()}
	{#if loading}
		<div class="flex flex-col gap-4 p-1">
			<Skeleton class="w-full h-36 rounded-md" />
			<Skeleton class="w-3/4 h-6" />
			<Skeleton class="w-1/2 h-4" />
			{@render tabsBar()}
			<Skeleton class="w-full h-20" />
			<Skeleton class="w-full h-32" />
		</div>
	{:else}
		<div class="flex flex-col gap-5 p-1">
			<ObjectHeader
				global={data?.global ?? null}
				localized={data?.localized ?? null}
				{fallbackName}
				leadingBadges={groupHeaderBadges}
				onShowGallery={() => {
					activeTab = 'images';
					appState.setImage(0);
				}}
			/>
			{@render tabsBar()}
			{#if notableMembers && notableMembers.length > 0}
				<MemberStrip
					members={notableMembers}
					localizedNames={memberNames}
					totalCount={memberTotal}
					heading={membersHeading}
					onSeeAll={() => (activeTab = 'members')}
				/>
			{/if}
			{#if isGroupMode && groupDetail?.global}
				<GroupStatCards global={groupDetail.global} />
			{/if}
			<ObjectDescription
				extract={data?.localized?.wikipedia?.extract}
				wikipediaUrl={data?.localized?.wikipedia?.url}
			/>
			{#if feature}
				<FeatureProperties {feature} detail={featureDetail} />
			{:else if body}
				<Physical global={data?.global ?? null} />
				<Orbital
					global={data?.global ?? null}
					localized={data?.localized ?? null}
					{body}
					orbitElements={drawerOrbitElements}
					{parentBody}
					jd={sampledJd}
				/>
				<Discovery global={data?.global ?? null} localized={data?.localized ?? null} />
				<Mission global={data?.global ?? null} localized={data?.localized ?? null} />
			{:else if isGroupMode}
				{#if groupDetail?.localized?.child_groups?.length}
					<ChildGroups childGroups={groupDetail.localized.child_groups} />
				{/if}
				<GroupProperties
					global={groupDetail?.global ?? null}
					localized={groupDetail?.localized ?? null}
				/>
			{/if}
			<ObjectLinks global={data?.global ?? null} localized={data?.localized ?? null} />
		</div>
	{/if}
{/snippet}

{#snippet imagesPanel()}
	<div class="flex flex-col gap-3 p-1">
		{@render tabsBar()}
		{#if viewerImages && viewerImages.length}
			<ImageGallery images={viewerImages} alt={displayName} />
		{/if}
	</div>
{/snippet}

{#snippet membersPanel()}
	<div class="flex flex-col gap-3 p-1">
		{@render tabsBar()}
		{#if notableMembers && notableMembers.length > 0}
			<MemberList
				members={notableMembers}
				localizedNames={memberNames}
				totalCount={memberTotal}
				heading={membersHeading}
			/>
		{/if}
	</div>
{/snippet}

{#if isMobile}
	<Vaul.Root
		open={true}
		{snapPoints}
		bind:activeSnapPoint
		shouldScaleBackground={false}
		dismissible={false}
	>
		<Vaul.Portal>
			<Vaul.Content
				trapFocus={false}
				class="fixed inset-x-0 bottom-0 z-50 flex h-dvh max-h-dvh flex-col rounded-t-xl border-t bg-background shadow-lg outline-none"
			>
				<div bind:this={headerEl} class="flex flex-col items-center gap-2 px-4 pt-3 pb-2">
					<div class="h-1 w-10 rounded-full bg-muted-foreground/40"></div>
					<div class="flex w-full items-center justify-between gap-2">
						<DrawerTitle {crumb} title={displayName} />
						<div class="flex items-center gap-1.5">
							<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={handleShare}>
								<Share2Icon />
								<span class="sr-only">{m.share()}</span>
							</Button>
							{#if showCameraButtons}
								{#if isMinimized}
									<Button
										variant="secondary"
										size="icon-lg"
										class="rounded-full"
										onclick={onMinimize}
									>
										<MinimizeIcon />
										<span class="sr-only">{m.zoom_out_to_system()}</span>
									</Button>
								{:else}
									<Button
										variant="secondary"
										size="icon-lg"
										class="rounded-full"
										onclick={onMaximize}
									>
										<MaximizeIcon />
										<span class="sr-only">{m.go_to_object()}</span>
									</Button>
								{/if}
							{/if}
							<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={onClose}>
								<XIcon />
								<span class="sr-only">{m.close()}</span>
							</Button>
						</div>
					</div>
				</div>
				<Tabs.Root bind:value={activeTab} class="flex flex-1 min-h-0 flex-col">
					<div
						class="flex-1 min-h-0 px-4 {isAtTop ? 'overflow-y-auto' : 'overflow-hidden'}"
						style="padding-bottom: calc(1rem + {HIDDEN_BOTTOM_DVH}dvh);"
					>
						<Tabs.Content value="overview">
							{@render overviewPanel()}
						</Tabs.Content>
						<Tabs.Content value="images">
							{@render imagesPanel()}
						</Tabs.Content>
						<Tabs.Content value="members">
							{@render membersPanel()}
						</Tabs.Content>
					</div>
				</Tabs.Root>
			</Vaul.Content>
		</Vaul.Portal>
	</Vaul.Root>
{:else}
	<!-- Desktop: side panel -->
	<aside
		class="fixed top-0 start-0 z-50 flex h-full w-[380px] max-w-[90vw] flex-col border-e bg-background shadow-lg"
	>
		<div class="flex items-center justify-between gap-2 p-2 px-4">
			<DrawerTitle {crumb} title={displayName} />
			<div class="flex items-center gap-1.5">
				<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={handleShare}>
					<Share2Icon />
					<span class="sr-only">{m.share()}</span>
				</Button>
				{#if showCameraButtons}
					{#if isMinimized}
						<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={onMinimize}>
							<MinimizeIcon />
							<span class="sr-only">{m.zoom_out_to_system()}</span>
						</Button>
					{:else}
						<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={onMaximize}>
							<MaximizeIcon />
							<span class="sr-only">{m.go_to_object()}</span>
						</Button>
					{/if}
				{/if}
				<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={onClose}>
					<XIcon />
					<span class="sr-only">{m.close()}</span>
				</Button>
			</div>
		</div>

		<Tabs.Root bind:value={activeTab} class="flex flex-1 min-h-0 flex-col">
			<ScrollArea class="flex-1 min-h-0">
				<Tabs.Content value="overview" class="px-4 pb-4">
					{@render overviewPanel()}
				</Tabs.Content>
				<Tabs.Content value="images" class="px-4 pb-4">
					{@render imagesPanel()}
				</Tabs.Content>
				<Tabs.Content value="members" class="px-4 pb-4">
					{@render membersPanel()}
				</Tabs.Content>
			</ScrollArea>
		</Tabs.Root>
	</aside>
{/if}

<!-- Mounted as a sibling of the drawer/aside, not a descendant: keeps the
     viewer's lifecycle and pointer events out of Vaul's drag detection and
     out of the drawer's CSS transform context. PhotoSwipe additionally
     appends its own DOM to document.body. -->
{#if viewerActive && viewerImages}
	<ImageViewer images={viewerImages} alt={displayName} />
{/if}
