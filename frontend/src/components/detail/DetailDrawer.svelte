<script lang="ts">
	import { getContext, untrack, type Snippet } from 'svelte';
	import { Button } from '$lib/components/ui/button/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { ObjectType } from '$lib/types/objects';
	import * as Tabs from '$lib/components/ui/tabs/index.js';
	import XIcon from '@lucide/svelte/icons/x';
	import Share2Icon from '@lucide/svelte/icons/share-2';
	import { ZoomInIcon, ZoomOutIcon } from '@lucide/svelte';
	import { toast } from 'svelte-sonner';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
	import RingStripBar from './charts/RingStripBar.svelte';
	import AtmosphereBandBar from './charts/AtmosphereBandBar.svelte';
	import MoonDiscRow from './charts/MoonDiscRow.svelte';
	import SurfaceMapBar from './charts/SurfaceMapBar.svelte';
	import MobileSheet from './frame/MobileSheet.svelte';
	import { topSnapPx } from '$lib/drawer';
	import { DetailLoad } from './state/detail-load.svelte';
	import TabsBar from './frame/TabsBar.svelte';
	import ActiveHero from './panels/ActiveHero.svelte';
	import { SurfaceState } from './state/surface-state.svelte';
	import { GalleryState } from './state/gallery-state.svelte';
	import OverviewPanel from './panels/OverviewPanel.svelte';
	import MembersPanel from './panels/MembersPanel.svelte';
	import FeaturesPanel from './panels/FeaturesPanel.svelte';
	import RingsPanel from './panels/RingsPanel.svelte';
	import StructurePanel from './panels/StructurePanel.svelte';
	import TargetsPanel from './panels/TargetsPanel.svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { DrawerTab } from '$lib/state/view';
	import {
		type Focusable,
		focusableFallbackName,
		focusableKey,
		type FocusFeature,
		type FocusObject
	} from '$lib/state/focusable';
	import DrawerTitle from './frame/DrawerTitle.svelte';
	import TravelButton from './travel/TravelButton.svelte';
	import LaunchSiteButton from './travel/LaunchSiteButton.svelte';
	import OrbitZoneButton from './travel/OrbitZoneButton.svelte';
	import { isLaunchSiteSlug } from '$lib/travel/launch-pad';
	import { orbitZoneTarget } from '$lib/travel/orbit-zone-target';
	import { parentCrumb, type Crumb } from '$lib/state/breadcrumb';
	import ImageViewer from '../image-viewer/ImageViewer.svelte';
	import ImagesPanel from './frame/ImagesPanel.svelte';
	import {
		ATMOSPHERE_GALLERY,
		FEATURES_GALLERY,
		MOONS_GALLERY,
		RINGS_GALLERY
	} from '$lib/fetch/objects/galleries';
	import MemberList from './members/MemberList.svelte';
	import TopicSummary from './sections/kit/TopicSummary.svelte';
	import SourcesFooter from './sections/SourcesFooter.svelte';
	import { promoteTabs, type TabItem } from './tab-visibility';
	import * as m from '$lib/paraglide/messages.js';
	import { categoryConfig } from '$lib/state/category-config';
	import { LineupHero } from './charts/lineup-hero.svelte';
	import { PlanetarySystemState } from './charts/planetary-system.svelte';
	import { MembersState } from './state/members-state.svelte';
	import { buildLineup, geometryFromMember } from './charts/lineup';

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
		// The mobile drawer portals out of <main>, so the parent's background-inert
		// can't reach it; it inerts itself behind the expanded mobile search.
		inert?: boolean;
	}

	let {
		focusable,
		clock,
		onClose,
		onMaximize,
		onMinimize,
		onSheetResize,
		inert = false
	}: Props = $props();

	let body = $derived(focusable.kind === 'group' ? null : focusable.body);
	let feature = $derived(focusable.kind === 'feature' ? focusable.feature : null);
	let isFeatureMode = $derived(focusable.kind === 'feature');
	let isGroupMode = $derived(focusable.kind === 'group');
	let groupSlug = $derived(focusable.kind === 'group' ? focusable.slug : null);
	/** The launch range this page is, when it is one — its pads are places a trip
	 *  can leave from. */
	let launchSiteSlug = $derived(
		focusable.kind === 'group' && isLaunchSiteSlug(focusable.slug) ? focusable.slug : null
	);
	/** The Earth-orbit zone this page is, when the planner holds an orbit in it —
	 *  somewhere a trip ends rather than leaves from. */
	let orbitZoneSlug = $derived(
		focusable.kind === 'group' && orbitZoneTarget(focusable.slug) ? focusable.slug : null
	);
	let cat = $derived(categoryConfig(focusable));

	const ctx = getContext<ContextManager>('ctx');
	const appState = getContext<AppState>('appState');
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');
	let parentBody = $derived(body ? ctx?.getBody(body.data.parentId) : undefined);

	// String key so the load effect ignores parent re-derivations that return a
	// new focusable ref with the same logical identity (replaceFocusName churn).
	let focusableId = $derived(focusableKey(focusable));
	const load = new DetailLoad({
		focusable: () => focusable,
		focusableId: () => focusableId
	});
	let data = $derived(load.data);
	let groupDetail = $derived(load.groupDetail);
	let loading = $derived(load.loading);
	// Surface-features model: gazetteer entries, quadrangle grid and the focused
	// feature's type page (see surface-state.svelte.ts).
	const surface = new SurfaceState({
		isGroupMode: () => isGroupMode,
		isFeatureMode: () => isFeatureMode,
		feature: () => feature,
		bodyId: () => body?.data.id,
		data: () => data,
		appState: () => appState
	});
	let isMobile = $state(false);

	$effect(() => {
		const mq = window.matchMedia('(max-width: 768px)');
		isMobile = mq.matches;
		const handler = (e: MediaQueryListEvent) => (isMobile = e.matches);
		mq.addEventListener('change', handler);
		return () => mq.removeEventListener('change', handler);
	});

	// The sheet height, held here so it survives a mobile↔desktop flip
	// unmounting the sheet (see MobileSheet.svelte).
	let activeSnapPoint = $state<number | string | null>('68px');

	// Re-pin a top-snapped sheet to the resized height: otherwise
	// activeSnapPoint is a stale px string absent from snapPoints, and vaul
	// refuses to re-snap. Lives here, not in MobileSheet, so a resize while the
	// sheet is unmounted (desktop interlude) still repairs it.
	$effect(() => {
		let prev = window.innerHeight;
		const update = () => {
			const next = window.innerHeight;
			if (activeSnapPoint === topSnapPx(prev)) activeSnapPoint = topSnapPx(next);
			prev = next;
		};
		window.addEventListener('resize', update);
		return () => window.removeEventListener('resize', update);
	});

	let crumb = $derived(
		parentCrumb(focusable, ctx, data, groupDetail?.global ?? null, surface.featureType)
	);

	let fallbackName = $derived(focusableFallbackName(focusable));
	// A planetary barycenter is the page for its whole system: the primary plus
	// every moon the scene has under it, drawn as the overview hero.
	const planetarySystem = new PlanetarySystemState({
		body: () => body,
		ctx: () => ctx
	});

	let resolvedName = $derived(
		(planetarySystem.isSystemPage ? planetarySystem.systemName : undefined) ??
			data?.localized?.name ??
			data?.global?.name ??
			fallbackName
	);
	let displayName = $derived(resolvedName ?? (loading ? m.loading() : focusableKey(focusable)));

	// Push the resolved name into the URL/title. On permanent failure, log once
	// per focusable and fall back to its key so the header isn't left empty.
	$effect(() => {
		// A failed load has no name to resolve — the alert panel speaks for it, and
		// warning "no name resolved" here would just be misleading.
		if (loading || load.loadError) return;
		// Stable key — avoids re-firing (and ping-ponging via replaceFocusName) on view churn.
		const key = focusableId;
		if (!resolvedName && !nameMissingLogged.has(key)) {
			nameMissingLogged.add(key);
			console.warn(`No name resolved for ${key} after detail fetch; using id as fallback.`);
		}
		appState.replaceFocusName(resolvedName ?? key);
	});
	// Flip to minimize well before the maximize target distance, so fly-to
	// overshoot can't strand the camera on the maximize side of an exact threshold.
	let isMinimized = $derived(
		appState && body ? appState.view.zoom <= minCameraDistance(body) * 20 : false
	);
	let showCameraButtons = $derived(!isFeatureMode && !isGroupMode);

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

	// Members model: the shared members tab, fragments, mission craft and the
	// overview strips they feed (see members-state.svelte.ts).
	const members = new MembersState({
		isGroupMode: () => isGroupMode,
		cat: () => cat,
		data: () => data,
		groupDetail: () => groupDetail,
		appState: () => appState
	});
	// Sphere-lineup hero + its imagery/metadata credits (see lineup-hero.svelte.ts).
	const lineup = new LineupHero({
		isGroupMode: () => isGroupMode,
		cat: () => cat,
		isPlanetBody: () => body?.data.objectType === ObjectType.PLANET,
		satellitesGroup: () => members.satellitesGroup,
		moonCount: () => data?.global?.moon_count ?? 0,
		fallbackName: () => fallbackName,
		// Opt-in: the two small-body categories say so in their config, and the
		// zones, flags and split-comet families through the category their
		// members belong to — none of them has a config entry.
		sphereLineup: () => cat.sphereLineup || groupDetail?.global?.applies_to === 'small_body',
		notableMembers: () => members.notableMembers,
		probes: () => members.probes,
		probeNames: () => members.probeNames,
		memberNames: () => members.memberNames,
		memberDescriptions: () => members.memberDescriptions,
		moonDescriptions: () => (isGroupMode ? undefined : data?.localized?.notable_moon_descriptions)
	});

	// Galleries + image-viewer model (see gallery-state.svelte.ts). The shelf
	// backdrop snippets stay here in the template, injected as a function.
	const gallery: GalleryState = new GalleryState({
		isGroupMode: () => isGroupMode,
		data: () => data,
		groupDetail: () => groupDetail,
		bodyId: () => body?.data.id,
		displayName: () => displayName,
		appState: () => appState,
		focusObject: () => focusObject,
		focusFeature: () => focusFeature,
		notableMembers: () => members.notableMembers,
		memberNames: () => members.memberNames,
		notableFeatures: () => surface.notableFeatures,
		featureNames: () => surface.featureNames,
		tabPresent: () => tabPresent,
		tabLabels: () => tabLabels,
		backdrop: (key) => shelfBackdrop(key)
	});
	let activeGallery = $derived(gallery.activeGallery);

	// The body cut open. Needs a layer model or a named atmosphere stack — the
	// ~30 bodies a mission actually constrained, not the 150,000 asteroids whose
	// interior is an estimate from a spectrum.
	let showStructureTab = $derived(
		!isGroupMode &&
			!isFeatureMode &&
			(!!data?.global?.interior?.layers?.length || !!data?.global?.atmosphere?.structure)
	);

	// Named rings, gaps and ringlets — the eight ringed bodies only.
	let ringFeatures = $derived(isGroupMode ? undefined : data?.global?.ring_features);
	let showRingsTab = $derived(Object.values(ringFeatures ?? {}).some((f) => !f.parent));

	let tabPresent = $derived<Record<DrawerTab, boolean>>({
		overview: true,
		targets: members.targetVisits.length > 0,
		images: gallery.hasImages,
		features: surface.showFeaturesTab,
		structure: showStructureTab,
		rings: showRingsTab,
		members: members.showMembersTab,
		fragments: members.showFragmentsTab,
		probes: members.showProbesTab
	});
	let tabCount = $derived(Object.values(tabPresent).filter(Boolean).length);

	// One ordered tab table: the bar renders it and the gallery's shelf links
	// read their labels off it, so the two can't diverge. Features, rings and
	// members carry no count — five figures of nomenclature (or a collection's
	// 1.38M) would crowd the bar past four tabs, and the page states each of
	// those totals anyway: the members total on a stat card, the others in
	// their own panel.
	let tabItems = $derived<TabItem[]>([
		{ tab: 'overview', label: m.tab_overview() },
		{ tab: 'targets', label: m.tab_targets(), count: members.targetVisits.length },
		{ tab: 'images', label: m.tab_images(), count: gallery.imageTotal },
		{ tab: 'features', label: m.tab_features() },
		{ tab: 'structure', label: m.tab_structure() },
		{ tab: 'rings', label: m.tab_rings() },
		{ tab: 'members', label: members.membersTabLabel },
		{ tab: 'fragments', label: m.tab_fragments(), count: members.fragmentTotal },
		{ tab: 'probes', label: m.tab_probes(), count: members.probeTotal }
	]);
	let tabLabels = $derived(
		Object.fromEntries(tabItems.map((t) => [t.tab, t.label])) as Partial<Record<DrawerTab, string>>
	);

	/** The body the ring-plane backdrop is drawn from — this page's own. */
	let ringStripId = $derived(body?.data.id);
	/** The air the Structure tab charts, for that shelf's backdrop. Needs the
	 *  layer stack: a composition bar alone has no picture to draw. */
	let shelfAtmosphere = $derived(
		data?.global?.atmosphere?.structure ? data.global.atmosphere : undefined
	);
	/** The body whose global map backs the surface shelf — the same texture the
	 *  Surface tab opens on, under its chart grid. */
	let surfaceMapId = $derived(
		!isGroupMode && data?.global?.map_texture_available ? body?.data.id : undefined
	);
	/** The moons the shelf is pooled from, for its backdrop. Built here rather
	 *  than taken from `lineup.hero`, which only exists on the bodies that earn
	 *  a sphere lineup — Mars has a moons shelf and two moons to draw. */
	let moonDiscs = $derived(
		isGroupMode
			? []
			: buildLineup(data?.global?.notable_moons ?? [], geometryFromMember, {
					names: data?.localized?.notable_moon_names
				})
	);

	/** The destination tab's own drawing, where it has one for this shelf. */
	function shelfBackdrop(key: string): Snippet | undefined {
		if (key === RINGS_GALLERY) return ringStripId ? ringPlaneTile : undefined;
		if (key === ATMOSPHERE_GALLERY) return shelfAtmosphere ? atmosphereBandTile : undefined;
		if (key === MOONS_GALLERY) return moonDiscs.length ? moonDiscTile : undefined;
		if (key === FEATURES_GALLERY) return surfaceMapId ? surfaceMapTile : undefined;
		return undefined;
	}

	let promotedTabs = $derived(promoteTabs(tabPresent, tabCount, isMobile));

	// URL-backed so it's deep-linkable. A tab whose content this object lacks
	// falls back to overview, never rendering empty.
	let activeTab = $derived<DrawerTab>(
		appState.view.tab && tabPresent[appState.view.tab] ? appState.view.tab : 'overview'
	);
	// A promoted tab drops the bar and takes the header instead: the object's name
	// moves into the crumb and the tab names the view. Still the same tab in the
	// URL — only the chrome around it differs.
	let soloTab = $derived<DrawerTab | null>(promotedTabs.has(activeTab) ? activeTab : null);
	// An open gallery only takes the header when its tab is solo; under the bar
	// the panel headlines it itself.
	let soloGallery = $derived(soloTab === 'images' ? activeGallery : undefined);
	let soloCrumb = $derived<Crumb | null>(
		soloGallery
			? { label: m.tab_images(), target: { kind: 'tab', tab: 'images' } }
			: soloTab
				? { label: displayName, target: { kind: 'tab', tab: 'overview' } }
				: null
	);
	let soloTitle = $derived(
		soloGallery
			? soloGallery.title
			: soloTab === 'images'
				? m.tab_images()
				: soloTab === 'probes'
					? m.tab_probes()
					: displayName
	);
	let barTabCount = $derived(tabCount - promotedTabs.size);

	/** A tab earns a place in the bar when the object has it and the bar kept it. */
	function inBar(tab: DrawerTab): boolean {
		return tabPresent[tab] && !promotedTabs.has(tab);
	}

	// URL's focus target, so a tile switching body and tab doesn't get its tab
	// wiped by the scrub below during the gap before the new focusable arrives.
	let viewFocusKey = $derived(
		appState.view.groupSlug
			? `group-${appState.view.groupSlug}`
			: appState.view.featureId != null
				? `feature-${appState.view.featureId}`
				: appState.view.id
	);
	// Scrub a deep-link tab pointing at absent content (e.g. ?tab=members on a
	// moonless body). The !loading guard avoids wiping a valid link mid-fetch,
	// while showMembersTab is still false.
	$effect(() => {
		const settled = viewFocusKey === focusableId;
		if (settled && !loading && appState.view.tab && activeTab === 'overview') {
			untrack(() => appState.setTab('overview'));
		}
	});

	// Same for a `&gal=` naming no shelf on this object — a stale link, or a
	// member gallery carried over from the collection it was opened on.
	$effect(() => {
		const settled = viewFocusKey === focusableId;
		if (settled && !loading && appState.view.gallery && !activeGallery) {
			untrack(() => appState.setGallery(null));
		}
	});
</script>

{#snippet tabsBar()}
	<TabsBar {activeTab} {barTabCount} {isMobile} {inBar} items={tabItems} />
{/snippet}

{#snippet activeHero()}
	<ActiveHero
		{body}
		{cat}
		{fallbackName}
		{activeTab}
		{load}
		{gallery}
		{surface}
		{members}
		{lineup}
		{planetarySystem}
	/>
{/snippet}

{#snippet ringPlaneTile()}
	<RingStripBar bodyId={ringStripId ?? ''} />
{/snippet}

{#snippet atmosphereBandTile()}
	{#if shelfAtmosphere}
		<AtmosphereBandBar
			structure={shelfAtmosphere.structure}
			species={shelfAtmosphere.composition?.species}
		/>
	{/if}
{/snippet}

{#snippet moonDiscTile()}
	<MoonDiscRow bodies={moonDiscs} />
{/snippet}

{#snippet surfaceMapTile()}
	<SurfaceMapBar bodyId={surfaceMapId ?? ''} />
{/snippet}

{#snippet imagesPanel()}
	<ImagesPanel
		galleries={gallery.galleries}
		active={activeGallery}
		headed={!soloGallery}
		alt={displayName}
		subjectName={(subject) => gallery.subjectNames.get(subject)}
		shelfLink={gallery.shelfLink}
		titles={isGroupMode ? groupDetail?.localized?.image_titles : data?.localized?.image_titles}
	/>
{/snippet}

{#snippet fragmentsPanel()}
	<div class="flex flex-col gap-4">
		{#if members.notableFragments && members.notableFragments.length > 0}
			<MemberList
				members={members.notableFragments}
				localizedNames={members.fragmentNames}
				focusMovesCamera={false}
			/>
		{/if}
	</div>
{/snippet}

{#snippet probesPanel()}
	<TopicSummary page={data?.localized?.probes_page} />
	{#if members.probes && members.probes.length > 0}
		<MemberList
			members={members.probes}
			localizedNames={members.probeNames}
			targetNames={members.probeTargetNames}
		/>
	{/if}
	<!-- The craft this tab draws are other people's meshes, several of them
	     share-alike; the credit rides where they render. -->
	{#if lineup.probeLineup}
		<SourcesFooter global={null} imagery={lineup.craftImagery} />
	{/if}
{/snippet}

{#snippet drawerToolbar()}
	{#if showCameraButtons}
		<Button
			size="icon-lg"
			class="rounded-full bg-foreground text-background hover:bg-foreground/90 hover:text-background"
			onclick={isMinimized ? onMinimize : onMaximize}
		>
			{#if isMinimized}
				<ZoomOutIcon />
				<span class="sr-only">{m.zoom_out_to_system()}</span>
			{:else}
				<ZoomInIcon />
				<span class="sr-only">{m.go_to_object()}</span>
			{/if}
		</Button>
	{/if}
	<!-- "How do I get here" belongs with the object, so it rides the panel's own
	     button row. Group panels have no body to fly to — except a launch site,
	     which is a place, and one trips leave from rather than go to, and an
	     Earth-orbit zone, which is where a trip ends without naming a body. -->
	{#if body}
		<TravelButton target={body.data} featureId={feature?.featureId ?? null} />
	{:else if launchSiteSlug}
		<LaunchSiteButton slug={launchSiteSlug} />
	{:else if orbitZoneSlug}
		<OrbitZoneButton slug={orbitZoneSlug} />
	{/if}
	<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={handleShare}>
		<Share2Icon />
		<span class="sr-only">{m.share()}</span>
	</Button>
	<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={onClose}>
		<XIcon />
		<span class="sr-only">{m.close()}</span>
	</Button>
{/snippet}

<!-- A promoted tab's panel, rendered outside Tabs.Root: with no trigger left in
     the bar there is nothing for a tabpanel to be labelled by, so it stops being
     one and becomes the drawer's only content. -->
{#snippet soloPanel(contentClass: string)}
	<div class={contentClass}>
		{#if soloTab === 'images'}
			{@render imagesPanel()}
		{:else if soloTab === 'probes'}
			{@render probesPanel()}
		{/if}
	</div>
{/snippet}

{#snippet tabPanels(contentClass: string | undefined)}
	<Tabs.Content value="overview" class={contentClass}>
		<OverviewPanel
			{body}
			{feature}
			{isGroupMode}
			{groupSlug}
			{cat}
			{clock}
			{load}
			{members}
			{surface}
			{lineup}
			{parentBody}
			{planetarySystem}
		/>
	</Tabs.Content>
	<Tabs.Content value="targets" class={contentClass}>
		<TargetsPanel visits={members.targetVisits} />
	</Tabs.Content>
	<Tabs.Content value="images" class={contentClass}>
		{@render imagesPanel()}
	</Tabs.Content>
	<Tabs.Content value="members" class={contentClass}>
		<MembersPanel {isGroupMode} {groupDetail} {body} {members} {lineup} />
	</Tabs.Content>
	<Tabs.Content value="features" class={contentClass}>
		<FeaturesPanel {body} {surface} {appState} />
	</Tabs.Content>
	<Tabs.Content value="rings" class={contentClass}>
		<RingsPanel {ringFeatures} {data} {body} {parentBody} {clock} {planetarySystem} />
	</Tabs.Content>
	<Tabs.Content value="structure" class={contentClass}>
		<StructurePanel {data} isBody={focusable.kind === 'body'} />
	</Tabs.Content>
	<Tabs.Content value="fragments" class={contentClass}>
		{@render fragmentsPanel()}
	</Tabs.Content>
	<Tabs.Content value="probes" class={contentClass}>
		{@render probesPanel()}
	</Tabs.Content>
{/snippet}

{#if isMobile}
	<MobileSheet
		{inert}
		bind:activeSnapPoint
		{onSheetResize}
		tab={activeTab}
		onTabChange={(v) => appState.setTab(v as DrawerTab)}
		solo={!!soloTab}
	>
		{#snippet header()}
			<DrawerTitle
				crumb={soloCrumb ?? crumb}
				title={soloTitle}
				ariaLabel={soloTab ? `${displayName} \u2014 ${soloTitle}` : undefined}
				id="detail-drawer-title"
			/>
			<div class="flex items-center gap-1.5">
				{@render drawerToolbar()}
			</div>
		{/snippet}
		{#if soloTab}
			<!-- A promoted tab keeps its hero: it belongs to the tab, not to the tab
			     bar, so losing the bar must not lose it. -->
			{@render activeHero()}
			{@render soloPanel('px-4 pt-4')}
		{:else}
			{@render activeHero()}
			{@render tabsBar()}
			{@render tabPanels('px-4 pt-4')}
		{/if}
	</MobileSheet>
{:else}
	<aside
		{inert}
		aria-labelledby="detail-drawer-title"
		class="fixed top-0 start-0 z-50 flex h-full w-[var(--detail-panel)] max-w-[90vw] flex-col border-e bg-background shadow-lg"
	>
		<!-- pt aligns the title/buttons row with the top-4 featured chips beside it. -->
		<div class="flex items-center justify-between gap-2 px-4 pb-2 pt-[18px]">
			<DrawerTitle
				crumb={soloCrumb ?? crumb}
				title={soloTitle}
				ariaLabel={soloTab ? `${displayName} \u2014 ${soloTitle}` : undefined}
				id="detail-drawer-title"
			/>
			<div class="flex items-center gap-1.5">
				{@render drawerToolbar()}
			</div>
		</div>

		{#if soloTab}
			<div class="flex flex-1 min-h-0 flex-col">
				<ScrollArea class="flex-1 min-h-0">
					{@render activeHero()}
					{@render soloPanel('px-4 pt-4 pb-4')}
				</ScrollArea>
			</div>
		{:else}
			<Tabs.Root
				value={activeTab}
				onValueChange={(v) => appState.setTab(v as DrawerTab)}
				class="flex flex-1 min-h-0 flex-col"
			>
				<ScrollArea class="flex-1 min-h-0">
					{@render activeHero()}
					{@render tabsBar()}
					{@render tabPanels('px-4 pt-4 pb-4')}
				</ScrollArea>
			</Tabs.Root>
		{/if}
	</aside>
{/if}

<!-- Sibling of the drawer, not a descendant: keeps its pointer events out of
     Vaul's drag detection and the drawer's transform context. -->
{#if gallery.viewerActive && gallery.viewerImages}
	<ImageViewer
		images={gallery.viewerImages}
		alt={displayName}
		subjectLink={(image) =>
			image.subject === undefined ? undefined : gallery.subjectLink(image.subject)}
	/>
{/if}
