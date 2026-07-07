<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import { Drawer as Vaul } from 'vaul-svelte';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import { groupTypeLabel, organizationRoleLabel, satelliteCategoryLabel } from '$lib/format/group';
	import GroupStatCards from './sections/GroupStatCards.svelte';
	import FragmentOf from './sections/FragmentOf.svelte';
	import SmallBodyGroupLinks from './sections/crossref/SmallBodyGroupLinks.svelte';
	import DwarfPlanetGroupLinks from './sections/crossref/DwarfPlanetGroupLinks.svelte';
	import PlanetGroupLinks from './sections/crossref/PlanetGroupLinks.svelte';
	import MoonGroupLinks from './sections/crossref/MoonGroupLinks.svelte';
	import ZoneCategoryLinks from './sections/crossref/ZoneCategoryLinks.svelte';
	import BodyCategoryTile from './sections/crossref/BodyCategoryTile.svelte';
	import { ObjectType } from '$lib/types/objects';
	import * as Tabs from '$lib/components/ui/tabs/index.js';
	import XIcon from '@lucide/svelte/icons/x';
	import Share2Icon from '@lucide/svelte/icons/share-2';
	import { ZoomInIcon, ZoomOutIcon } from '@lucide/svelte';
	import { toast } from 'svelte-sonner';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
	import { fetchObjectDetail, type ObjectDetailData } from '$lib/fetch/objects/object-data';
	import { fetchFeatureDetail, type FeatureDetailData } from '$lib/fetch/nomenclature/details';
	import { fetchGroupDetail, type GroupDetailData } from '$lib/fetch/groups/details';
	import { fetchGroupIndex, CAT_SOLAR_SYSTEM } from '$lib/fetch/groups/registry';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { DrawerTab } from '$lib/state/view';
	import { type Focusable, focusableFallbackName, focusableKey } from '$lib/state/focusable';
	import ObjectHeader from './frame/ObjectHeader.svelte';
	import DrawerTitle from './frame/DrawerTitle.svelte';
	import { parentCrumb, parentPlanet } from '$lib/state/breadcrumb';
	import ImageViewer from '../image-viewer/ImageViewer.svelte';
	import ImageGallery from './frame/ImageGallery.svelte';
	import ObjectDescription from './sections/ObjectDescription.svelte';
	import SourcesFooter from './sections/SourcesFooter.svelte';
	import Physical from './sections/Physical.svelte';
	import ObjectStats from './sections/ObjectStats.svelte';
	import SatCrossRefs from './sections/SatCrossRefs.svelte';
	import Orbital from './sections/Orbital.svelte';
	import Discovery from './sections/Discovery.svelte';
	import Mission from './sections/Mission.svelte';
	import GroupProperties from './sections/GroupProperties.svelte';
	import GroupOrbitMap from './charts/GroupOrbitMap.svelte';
	import MoonsPerPlanetChart from './charts/MoonsPerPlanetChart.svelte';
	import ChildGroups from './sections/ChildGroups.svelte';
	import { categoryPlotType, classNameFromSlug, scatterZoneSlugs } from '$lib/charts/orbit-zones';
	import FeatureProperties from './sections/FeatureProperties.svelte';
	import MemberStrip, { STRIP_CAPACITY } from './members/MemberStrip.svelte';
	import MemberList from './members/MemberList.svelte';
	import PaginatedMemberList from './members/PaginatedMemberList.svelte';
	import BodyLineup from './charts/BodyLineup.svelte';
	import SolarSystemMap from './charts/SolarSystemMap.svelte';
	import CategoryCrossRefs from './sections/crossref/CategoryCrossRefs.svelte';
	import CategoryChildTiles from './sections/crossref/CategoryChildTiles.svelte';
	import PlanetMassChart from './charts/PlanetMassChart.svelte';
	import SolarSystemMassChart from './charts/SolarSystemMassChart.svelte';
	import ObjectLinks from './sections/ObjectLinks.svelte';
	import { formatCompactNumber } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';
	import { categoryConfig } from '$lib/state/category-config';
	import { featureDetailToObjectData, groupDetailToObjectData } from '$lib/state/detail-adapters';
	import { LineupHero } from './charts/lineup-hero.svelte';
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';

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
	let cat = $derived(categoryConfig(focusable));
	let groupHeaderBadges = $derived.by(() => {
		const g = groupDetail?.global;
		if (!g) return undefined;
		const out: string[] = [groupTypeLabel(g.type)];
		for (const role of g.roles ?? []) out.push(organizationRoleLabel(role));
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
	// Asteroid/comet SBDB zones (orbit_class), distinct from earth_orbit_class
	// satellite zones; their overview drops the notable-members strip.
	let isSmallBodyZone = $derived(groupDetail?.global?.type === 'orbit_class');
	// A small-body zone's orbit-class name (e.g. "MBA"), for its category tiles.
	let smallBodyZoneClass = $derived(
		isSmallBodyZone && focusable.kind === 'group' ? classNameFromSlug(focusable.slug) : null
	);
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
			fetchFeatureDetail(current.body.data.id, f.featureId)
				.then((detail) => {
					if (focusableId !== key) return;
					featureDetail = detail;
					data = featureDetailToObjectData(detail, f);
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
					data = groupDetailToObjectData(detail, slug);
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
	const MID_SNAP = 0.3;
	// The open drawer's top edge meets the collapsed search bar's top (it's
	// pinned at top-4 = 16px), covering it while leaving that same sliver of map
	// above. A px snap keeps the edge at a fixed inset on any viewport height.
	const TOP_GAP_PX = 16;

	let innerH = $state(typeof window === 'undefined' ? 800 : window.innerHeight);
	$effect(() => {
		let prev = window.innerHeight;
		const update = () => {
			const next = window.innerHeight;
			// Re-pin a top-snapped drawer to the new height-derived snap. Without
			// this, a viewport resize (mobile keyboard shrinking innerHeight)
			// leaves activeSnapPoint on a px string that no longer exists in
			// snapPoints, and vaul silently refuses to re-snap — the sheet freezes
			// at a stale offset until reload.
			if (activeSnapPoint === `${Math.max(1, prev - TOP_GAP_PX)}px`) {
				activeSnapPoint = `${Math.max(1, next - TOP_GAP_PX)}px`;
			}
			prev = next;
			innerH = next;
		};
		window.addEventListener('resize', update);
		return () => window.removeEventListener('resize', update);
	});

	let headerEl = $state<HTMLDivElement | null>(null);
	// Initial guess close to the rendered size (icon-lg row + handle + paddings)
	// so the drawer opens at a sensible height before the first measurement.
	let headerHeightPx = $state(68);
	let collapsedSnap = $derived(`${headerHeightPx}px`);
	let topSnap = $derived(`${Math.max(1, innerH - TOP_GAP_PX)}px`);
	let snapPoints = $derived([collapsedSnap, MID_SNAP, topSnap]);
	let activeSnapPoint = $state<number | string | null>('68px');
	let isAtTop = $derived(activeSnapPoint === topSnap);

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

	// Categories render the orbit map here; class/NEO/PHA pages get it from
	// GroupProperties (slug-derived). Chips fold into GroupOrbitMap, so both show them.
	let categoryPlot = $derived(focusable.kind === 'group' ? categoryPlotType(focusable.slug) : null);
	// Moons category: the per-planet/dwarf bar chart replaces the notable-members
	// strip and members list this page deliberately omits.
	let moonCounts = $derived(cat.moons ? groupDetail?.global?.moon_counts : undefined);
	let visibleChildGroups = $derived.by(() => {
		// Bus chips live in GroupProperties; zones live in the orbit map;
		// constellations fold into the top-constellations bar chart when present.
		const hasConstellationBars = (groupDetail?.localized?.constellations?.length ?? 0) > 0;
		const cg = (groupDetail?.localized?.child_groups ?? []).filter(
			(c) => c.role !== 'bus' && !(hasConstellationBars && c.role === 'constellation')
		);
		if (!categoryPlot) return cg;
		const onScatter = scatterZoneSlugs(categoryPlot);
		return cg.filter((c) => !(c.primary_id && onScatter.has(c.primary_id)));
	});
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
	// Earth folds its artificial satellites into the moons section: the Moon plus
	// curated featured sats (ISS, Hubble, Starlink), "+N more" → the group page.
	let satellitesGroup = $derived(isGroupMode ? undefined : data?.global?.satellites_group);
	// "+N more" must match the count shown on the Satellites group page, which is
	// the categorized member total (primary orbit classes) — not Earth's raw
	// satcat tally (`satellite_count` includes debris/uncategorized objects). The
	// group index `n` is that same baked member count.
	let satelliteGroupCount = $state(0);
	$effect(() => {
		const slug = satellitesGroup;
		if (!slug) return;
		fetchGroupIndex().then((idx) => (satelliteGroupCount = idx[slug]?.n ?? 0));
	});
	// The members tab is shared: groups list notable members, bodies list moons.
	let notableMembers = $derived(
		isGroupMode
			? groupDetail?.global?.notable_members
			: satellitesGroup
				? [...(data?.global?.notable_moons ?? []), ...(data?.global?.notable_satellites ?? [])]
				: data?.global?.notable_moons
	);
	let memberNames = $derived(
		isGroupMode
			? groupDetail?.localized?.notable_member_names
			: satellitesGroup
				? { ...data?.localized?.notable_moon_names, ...data?.localized?.notable_satellite_names }
				: data?.localized?.notable_moon_names
	);
	let memberDescriptions = $derived(
		isGroupMode ? groupDetail?.localized?.notable_member_descriptions : undefined
	);
	// Sphere-lineup hero + its imagery/metadata credits (see lineup-hero.svelte.ts).
	const lineup = new LineupHero({
		isGroupMode: () => isGroupMode,
		cat: () => cat,
		isPlanetBody: () => body?.data.objectType === ObjectType.PLANET,
		satellitesGroup: () => satellitesGroup,
		moonCount: () => data?.global?.moon_count ?? 0,
		fallbackName: () => fallbackName,
		notableMembers: () => notableMembers,
		memberNames: () => memberNames,
		memberDescriptions: () => memberDescriptions,
		moonDescriptions: () => (isGroupMode ? undefined : data?.localized?.notable_moon_descriptions)
	});
	let memberTotal = $derived(
		isGroupMode
			? (groupDetail?.global?.member_count ?? 0)
			: (data?.global?.moon_count ?? 0) + (satellitesGroup ? satelliteGroupCount : 0)
	);
	// A split-comet family group lists fragments; a mission group lists its craft.
	let isSplitCometGroup = $derived(groupDetail?.global?.type === 'split_comet');
	let isMissionGroup = $derived(groupDetail?.global?.type === 'mission');
	// Earth sats (and every earth-sat group page: launch vehicles, organizations,
	// launch sites, countries, …) draw on CelesTrak SATCAT + GCAT for metadata.
	let earthSatCredit = $derived(
		isGroupMode
			? groupDetail?.global?.applies_to === 'earth_sat'
			: data?.global?.cross_refs?.norad_cat_id != null
	);
	let membersHeading = $derived(
		isGroupMode
			? isSplitCometGroup
				? m.fragments_section()
				: isMissionGroup
					? m.mission_members_section()
					: m.members_notable()
			: satellitesGroup
				? m.satellites_section()
				: m.moons_section()
	);
	let membersTabLabel = $derived(
		isGroupMode
			? isSplitCometGroup
				? m.tab_fragments()
				: isMissionGroup
					? m.mission_members_section()
					: m.tab_members()
			: m.tab_moons()
	);
	let hasMembers = $derived(!!notableMembers && notableMembers.length > 0);
	// Tab only earns its place past the overview strip's capacity; ≤5 fit there.
	// Earth's Satellites strip sends "+N more" to the group, so no in-drawer tab.
	// The planet/moon lineups already cross-link every member, so they need neither.
	let showMembersTab = $derived(
		hasMembers && !satellitesGroup && memberTotal > STRIP_CAPACITY && !cat.lineup
	);

	function seeAllMembers() {
		if (satellitesGroup) appState?.setGroup(satellitesGroup, membersHeading);
		else appState.setTab('members');
	}

	// Split-comet fragments: a strip + tab on the intact parent comet, mirroring
	// moons. `fragment_of` (the fragment side) drives the breadcrumb + a card.
	let notableFragments = $derived(isGroupMode ? undefined : data?.global?.fragments);
	let fragmentNames = $derived(data?.localized?.fragment_names);
	let fragmentTotal = $derived(data?.global?.fragment_count ?? 0);
	let fragmentOf = $derived(isGroupMode ? undefined : data?.global?.fragment_of);
	// Small body → its SBDB orbit-class group. Suppressed on fragments: they
	// point to their parent comet instead
	let orbitClass = $derived(isGroupMode || fragmentOf ? undefined : data?.global?.sbdb?.class);
	// NEO/PHA crossref tile alongside the orbit-class one (rendered only under the
	// `orbitClass` branch, so no group/fragment guard needed). PHA is the NEO
	// subset, so prefer it when both apply — a single flag tile, never two.
	let smallBodyFlag = $derived(
		data?.global?.sbdb?.pha
			? ('pha' as const)
			: data?.global?.sbdb?.neo
				? ('neo' as const)
				: undefined
	);
	let isPlanetBody = $derived(body?.data.objectType === ObjectType.PLANET);
	let isDwarfPlanetBody = $derived(body?.data.objectType === ObjectType.DWARF_PLANET);
	let isMoonBody = $derived(body?.data.objectType === ObjectType.MOON);
	// A moon's host planet (resolved past the nameless barycenter) for its tile.
	let moonParent = $derived(isMoonBody && body ? parentPlanet(ctx, body.data.parentId) : undefined);
	let isStarBody = $derived(body?.data.objectType === ObjectType.STAR);
	let hasFragments = $derived(!!notableFragments && notableFragments.length > 0);
	let showFragmentsTab = $derived(hasFragments && fragmentTotal > STRIP_CAPACITY);

	function seeAllFragments() {
		appState.setTab('fragments');
	}

	// Probe mission: the mission cross-ref tile lives in SatCrossRefs now; the
	// primary craft still shows a strip of its sibling craft below.
	let missionMembers = $derived(isGroupMode ? undefined : data?.global?.mission_members);
	let missionMemberNames = $derived(data?.localized?.mission_member_names);
	let missionMemberTotal = $derived(data?.global?.mission_member_count ?? 0);
	let hasMissionMembers = $derived(!!missionMembers && missionMembers.length > 0);

	function seeAllMissionMembers() {
		const link = data?.global?.mission;
		if (link) appState?.setGroup(link.primary_id, link.name);
	}

	// Overview member strips (same card UI, different sources): body moons/sats,
	// split-comet fragments, mission craft. Lineup/small-body/Solar-System pages
	// route members through their own hero or tab, so drop the plain strip.
	interface OverviewStrip {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
		totalCount: number;
		heading: string;
		onSeeAll: () => void;
		focusMovesCamera?: boolean;
	}
	let overviewStrips = $derived.by(() => {
		const strips: OverviewStrip[] = [];
		if (
			notableMembers &&
			notableMembers.length > 0 &&
			!cat.lineup &&
			!cat.solarSystem &&
			!isSmallBodyZone &&
			!cat.smallBody
		) {
			strips.push({
				members: notableMembers,
				localizedNames: memberNames,
				totalCount: memberTotal,
				heading: membersHeading,
				onSeeAll: seeAllMembers
			});
		}
		if (hasFragments && notableFragments) {
			strips.push({
				members: notableFragments,
				localizedNames: fragmentNames,
				totalCount: fragmentTotal,
				heading: m.fragments_section(),
				onSeeAll: seeAllFragments,
				focusMovesCamera: false
			});
		}
		if (hasMissionMembers && missionMembers) {
			strips.push({
				members: missionMembers,
				localizedNames: missionMemberNames,
				totalCount: missionMemberTotal,
				heading: m.mission_members_section(),
				onSeeAll: seeAllMissionMembers
			});
		}
		return strips;
	});
	// URL-backed so it's deep-linkable. A tab whose content this object lacks
	// falls back to overview, never rendering empty.
	let activeTab = $derived<DrawerTab>(
		appState.view.tab === 'images' && hasImages
			? 'images'
			: appState.view.tab === 'members' && showMembersTab
				? 'members'
				: appState.view.tab === 'fragments' && showFragmentsTab
					? 'fragments'
					: 'overview'
	);
	// Scrub a deep-link tab pointing at absent content (e.g. ?tab=members on a
	// moonless body). The !loading guard avoids wiping a valid link mid-fetch,
	// while showMembersTab is still false.
	$effect(() => {
		if (!loading && appState.view.tab && activeTab === 'overview') {
			untrack(() => appState.setTab('overview'));
		}
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
			{#if showMembersTab}
				<Tabs.Trigger value="members" class="px-2">
					{membersTabLabel}
					<Badge variant="secondary" class="text-[10px] py-0 px-1.5 h-4 leading-none">
						{formatCompactNumber(memberTotal)}
					</Badge>
				</Tabs.Trigger>
			{/if}
			{#if showFragmentsTab}
				<Tabs.Trigger value="fragments" class="px-2">
					{m.tab_fragments()}
					<Badge variant="secondary" class="text-[10px] py-0 px-1.5 h-4 leading-none">
						{formatCompactNumber(fragmentTotal)}
					</Badge>
				</Tabs.Trigger>
			{/if}
		</Tabs.List>
	</div>
{/snippet}

{#snippet lineupHeroSnippet()}
	{#if lineup.hero}
		<BodyLineup
			bodies={lineup.hero.bodies}
			ariaLabel={lineup.hero.ariaLabel}
			perPage={lineup.hero.perPage}
		/>
	{/if}
{/snippet}

{#snippet solarSystemMapSnippet()}
	<SolarSystemMap ariaLabel={fallbackName} localizedNames={memberNames} />
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
				hero={cat.solarSystem
					? solarSystemMapSnippet
					: lineup.hero && !lineup.isMoonLineup
						? lineupHeroSnippet
						: undefined}
				onShowGallery={() => {
					appState.setTab('images');
					appState.setImage(0);
				}}
			/>
			{@render tabsBar()}
			{#if isGroupMode && groupDetail?.global}
				<GroupStatCards global={groupDetail.global} {showMembersTab} />
			{:else if body}
				<ObjectStats
					global={data?.global ?? null}
					{body}
					orbitElements={drawerOrbitElements}
					{parentBody}
					jd={sampledJd}
				/>
			{/if}
			<ObjectDescription
				extract={data?.localized?.wikipedia?.extract}
				wikipediaUrl={data?.localized?.wikipedia?.url}
			/>
			{#if fragmentOf}
				<FragmentOf {fragmentOf} />
			{/if}
			{#if isPlanetBody}
				<PlanetGroupLinks />
			{:else if isDwarfPlanetBody}
				<DwarfPlanetGroupLinks {orbitClass} />
			{:else if isMoonBody}
				<MoonGroupLinks
					parentId={moonParent?.data.id ?? body?.data.parentId}
					parentName={moonParent?.data.name ?? data?.global?.parent_name}
				/>
			{:else if isStarBody}
				<BodyCategoryTile slug={CAT_SOLAR_SYSTEM} />
			{:else if orbitClass}
				<SmallBodyGroupLinks {orbitClass} flag={smallBodyFlag} />
			{/if}
			{#if body}
				<SatCrossRefs
					global={data?.global ?? null}
					localized={data?.localized ?? null}
					orbitElements={drawerOrbitElements}
					{body}
					jd={sampledJd}
				/>
			{/if}
			{#each overviewStrips as strip (strip.heading)}
				<MemberStrip
					members={strip.members}
					localizedNames={strip.localizedNames}
					totalCount={strip.totalCount}
					heading={strip.heading}
					onSeeAll={strip.onSeeAll}
					focusMovesCamera={strip.focusMovesCamera ?? true}
				/>
			{/each}
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
				{#if cat.crossRefs && focusable.kind === 'group'}
					<CategoryCrossRefs slug={focusable.slug} />
				{/if}
				{#if smallBodyZoneClass}
					<ZoneCategoryLinks className={smallBodyZoneClass} />
				{/if}
				{#if cat.solarSystem && visibleChildGroups.length}
					<CategoryChildTiles childGroups={visibleChildGroups} />
				{/if}
				{#if cat.planets && notableMembers && notableMembers.length > 0}
					<PlanetMassChart members={notableMembers} localizedNames={memberNames} />
				{/if}
				{#if cat.solarSystem}
					<SolarSystemMassChart />
				{/if}
				{#if moonCounts && moonCounts.length > 0}
					<MoonsPerPlanetChart entries={moonCounts} />
				{/if}
				{#if categoryPlot && groupDetail?.global}
					<GroupOrbitMap global={groupDetail.global} plotOverride={categoryPlot} />
				{/if}
				{#if visibleChildGroups.length && !cat.solarSystem}
					<ChildGroups childGroups={visibleChildGroups} />
				{/if}
				<GroupProperties
					global={groupDetail?.global ?? null}
					localized={groupDetail?.localized ?? null}
				/>
			{/if}
			<ObjectLinks global={data?.global ?? null} localized={data?.localized ?? null} />
			<SourcesFooter
				global={data?.global ?? null}
				earthSat={earthSatCredit}
				wikipediaLicensed={!!data?.localized?.wikipedia?.extract}
				pck={lineup.overviewCredits.pck}
				sbdb={lineup.overviewCredits.sbdb}
				wikidata={lineup.overviewCredits.wikidata}
				imagery={lineup.overviewCredits.imagery}
			/>
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
		<!-- The lineup is this tab's hero; its imagery/size credits ride at the
		     foot here, where the spheres render — not the overview footer. -->
		{#if lineup.isMoonLineup}
			{@render lineupHeroSnippet()}
		{/if}
		<!-- Solar System: the minimap is the page hero, so the sphere lineup lives
		     here in the members tab (paginated). -->
		{#if lineup.solarSystemLineup}
			<BodyLineup
				bodies={lineup.solarSystemLineup.bodies}
				ariaLabel={fallbackName}
				perPage={lineup.solarSystemLineup.perPage}
			/>
		{/if}
		{@render tabsBar()}
		{#if isGroupMode && groupDetail?.global}
			<PaginatedMemberList
				source={{ kind: 'group', slug: groupDetail.global.slug }}
				totalCount={memberTotal}
				localizedNames={memberNames}
				fallback={notableMembers ?? []}
			/>
		{:else if body && notableMembers && notableMembers.length > 0}
			<PaginatedMemberList
				source={{ kind: 'parent', parentId: body.data.id }}
				totalCount={memberTotal}
				localizedNames={memberNames}
				fallback={notableMembers}
			/>
		{/if}
		{#if lineup.isMoonLineup}
			<SourcesFooter global={null} pck={lineup.pck} imagery={lineup.imagery} />
		{/if}
	</div>
{/snippet}

{#snippet fragmentsPanel()}
	<div class="flex flex-col gap-3 p-1">
		{@render tabsBar()}
		{#if notableFragments && notableFragments.length > 0}
			<MemberList
				members={notableFragments}
				localizedNames={fragmentNames}
				focusMovesCamera={false}
			/>
		{/if}
	</div>
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
	<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={handleShare}>
		<Share2Icon />
		<span class="sr-only">{m.share()}</span>
	</Button>
	<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={onClose}>
		<XIcon />
		<span class="sr-only">{m.close()}</span>
	</Button>
{/snippet}

{#snippet tabPanels(contentClass: string | undefined)}
	<Tabs.Content value="overview" class={contentClass}>
		{@render overviewPanel()}
	</Tabs.Content>
	<Tabs.Content value="images" class={contentClass}>
		{@render imagesPanel()}
	</Tabs.Content>
	<Tabs.Content value="members" class={contentClass}>
		{@render membersPanel()}
	</Tabs.Content>
	<Tabs.Content value="fragments" class={contentClass}>
		{@render fragmentsPanel()}
	</Tabs.Content>
{/snippet}

{#if isMobile}
	<Vaul.Root
		open={true}
		{snapPoints}
		bind:activeSnapPoint
		shouldScaleBackground={false}
		dismissible={false}
		repositionInputs={false}
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
							{@render drawerToolbar()}
						</div>
					</div>
				</div>
				<Tabs.Root
					value={activeTab}
					onValueChange={(v) => appState.setTab(v as DrawerTab)}
					class="flex flex-1 min-h-0 flex-col"
				>
					<div
						class="flex-1 min-h-0 px-4 {isAtTop ? 'overflow-y-auto' : 'overflow-hidden'}"
						style="padding-bottom: calc(1rem + {TOP_GAP_PX}px + var(--safe-bottom));"
					>
						{@render tabPanels(undefined)}
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
		<!-- pt aligns the title/buttons row with the top-4 featured chips beside it. -->
		<div class="flex items-center justify-between gap-2 px-4 pb-2 pt-[18px]">
			<DrawerTitle {crumb} title={displayName} />
			<div class="flex items-center gap-1.5">
				{@render drawerToolbar()}
			</div>
		</div>

		<Tabs.Root
			value={activeTab}
			onValueChange={(v) => appState.setTab(v as DrawerTab)}
			class="flex flex-1 min-h-0 flex-col"
		>
			<ScrollArea class="flex-1 min-h-0">
				{@render tabPanels('px-4 pb-4')}
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
