<script lang="ts">
	import { getContext, untrack, type Snippet } from 'svelte';
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
	import FeatureGroupLinks from './sections/crossref/FeatureGroupLinks.svelte';
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
	import { pickImageUrl } from '$lib/fetch/objects/images';
	import { fetchFeatureDetail, type FeatureDetailData } from '$lib/fetch/nomenclature/details';
	import {
		fetchBodyQuadrangles,
		fetchQuadrangleText,
		type Quadrangle,
		type QuadrangleText
	} from '$lib/fetch/nomenclature/quadrangles';
	import SurfaceHero from './sections/SurfaceHero.svelte';
	import RingCatalog from './sections/RingCatalog.svelte';
	import GalleryHero from './sections/GalleryHero.svelte';
	import RingStripBar from './charts/RingStripBar.svelte';
	import AtmosphereBandBar from './charts/AtmosphereBandBar.svelte';
	import MoonDiscRow from './charts/MoonDiscRow.svelte';
	import SurfaceMapBar from './charts/SurfaceMapBar.svelte';
	import FeatureTypeFilter from './sections/FeatureTypeFilter.svelte';
	import { fetchGroupDetail, type GroupDetailData } from '$lib/fetch/groups/details';
	import {
		fetchGroupIndex,
		featureTypeSlug,
		CAT_RING_SYSTEMS,
		CAT_SOLAR_SYSTEM
	} from '$lib/fetch/groups/registry';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { focusHref, groupHref, imageHref, tabHref } from '$lib/state/focus-link';
	import type { DrawerTab } from '$lib/state/view';
	import { applyFeature, serializeUrl } from '$lib/state/url';
	import {
		type Focusable,
		focusableFallbackName,
		focusableKey,
		type FocusFeature,
		type FocusObject
	} from '$lib/state/focusable';
	import ObjectHeader from './frame/ObjectHeader.svelte';
	import DrawerTitle from './frame/DrawerTitle.svelte';
	import { parentCrumb, parentPlanet, type Crumb } from '$lib/state/breadcrumb';
	import ImageViewer from '../image-viewer/ImageViewer.svelte';
	import ImagesPanel from './frame/ImagesPanel.svelte';
	import {
		ATMOSPHERE_GALLERY,
		buildGalleries,
		FEATURES_GALLERY,
		findGallery,
		imageCount,
		MAIN_GALLERY,
		MOONS_GALLERY,
		RINGS_GALLERY,
		type Gallery,
		type ShelfLink
	} from '$lib/fetch/objects/galleries';
	import ObjectDescription from './sections/ObjectDescription.svelte';
	import SourcesFooter from './sections/SourcesFooter.svelte';
	import Bulk from './sections/Bulk.svelte';
	import Brightness from './sections/Brightness.svelte';
	import Atmosphere from './sections/Atmosphere.svelte';
	import Interior from './sections/Interior.svelte';
	import Rings from './sections/Rings.svelte';
	import RingStatCards from './sections/RingStatCards.svelte';
	import Structure from './sections/Structure.svelte';
	import StructureStatCards from './sections/StructureStatCards.svelte';
	import ObjectStats from './sections/ObjectStats.svelte';
	import SatCrossRefs from './sections/SatCrossRefs.svelte';
	import Orbital from './sections/Orbital.svelte';
	import Discovery from './sections/Discovery.svelte';
	import Mission from './sections/Mission.svelte';
	import GroupProperties from './sections/GroupProperties.svelte';
	import GroupOrbitMap from './charts/GroupOrbitMap.svelte';
	import CountPerBodyChart from './charts/CountPerBodyChart.svelte';
	import ChildGroups from './sections/ChildGroups.svelte';
	import FeatureTypeFamilies from './sections/FeatureTypeFamilies.svelte';
	import { categoryPlotType, classNameFromSlug, scatterZoneSlugs } from '$lib/charts/orbit-zones';
	import FeatureProperties from './sections/FeatureProperties.svelte';
	import FeatureStatCards from './sections/FeatureStatCards.svelte';
	import MemberStrip, { STRIP_CAPACITY } from './members/MemberStrip.svelte';
	import MemberList from './members/MemberList.svelte';
	import PaginatedMemberList from './members/PaginatedMemberList.svelte';
	import BodyLineup from './charts/BodyLineup.svelte';
	import SolarSystemMap from './charts/SolarSystemMap.svelte';
	import CategoryCrossRefs from './sections/crossref/CategoryCrossRefs.svelte';
	import CategoryChildTiles from './sections/crossref/CategoryChildTiles.svelte';
	import RingSystemTiles from './sections/crossref/RingSystemTiles.svelte';
	import PlanetMassChart from './charts/PlanetMassChart.svelte';
	import RingMassChart from './charts/RingMassChart.svelte';
	import SolarSystemMassChart from './charts/SolarSystemMassChart.svelte';
	import ObjectLinks from './sections/ObjectLinks.svelte';
	import { formatCompactNumber } from '$lib/format/quantities';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { categoryConfig } from '$lib/state/category-config';
	import { featureTypeLabel } from '$lib/format/feature-type';
	import { featureDetailToObjectData, groupDetailToObjectData } from '$lib/state/detail-adapters';
	import { LineupHero } from './charts/lineup-hero.svelte';
	import { buildLineup, geometryFromMember } from './charts/lineup';
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
	// The focused feature's type page (`ft-<slug>`), for the breadcrumb + cross-ref
	// tile. The slug lives in the group index, so it resolves asynchronously;
	// untracked so writing the result doesn't re-run the lookup.
	let featureType = $state<{ slug: string; label: string } | null>(null);
	$effect(() => {
		const code = feature?.typeCode;
		if (!code) {
			featureType = null;
			return;
		}
		untrack(() => {
			featureTypeSlug(code).then((slug) => {
				if (feature?.typeCode !== code) return;
				const label = featureTypeLabel(slug);
				featureType = slug && label ? { slug, label } : null;
			});
		});
	});
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
	const focusObject = getContext<FocusObject | undefined>('focusObject');
	const focusFeature = getContext<FocusFeature | undefined>('focusFeature');
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
	// Set when the detail fetch rejects — drives an alert panel instead of an
	// empty drawer. `retryNonce` re-triggers the load effect on a retry click.
	let loadError = $state(false);
	let retryNonce = $state(0);
	function retryLoad() {
		retryNonce++;
	}
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
		void retryNonce; // re-run on retry
		const current = untrack(() => focusable);
		loading = true;
		loadError = false;
		data = null;
		featureDetail = null;
		groupDetail = null;
		// A rejected detail fetch used to rethrow into the void, leaving an empty
		// drawer. Surface it as an alert panel instead; stale loads (key moved on)
		// are ignored so an old failure can't overwrite a newer focus.
		const onError = (err: unknown) => {
			if (focusableId !== key) return;
			console.warn(`[detail] failed to load ${key}:`, err);
			loading = false;
			loadError = true;
		};
		if (current.kind === 'feature') {
			const f = current.feature;
			fetchFeatureDetail(current.body.data.id, f.featureId)
				.then((detail) => {
					if (focusableId !== key) return;
					featureDetail = detail;
					data = featureDetailToObjectData(detail, f);
					loading = false;
				})
				.catch(onError);
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
				.catch(onError);
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
			.catch(onError);
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

	let crumb = $derived(parentCrumb(focusable, ctx, data, groupDetail?.global ?? null, featureType));

	// Categories render the orbit map here; class/NEO/PHA pages get it from
	// GroupProperties (slug-derived). Chips fold into GroupOrbitMap, so both show them.
	let categoryPlot = $derived(focusable.kind === 'group' ? categoryPlotType(focusable.slug) : null);
	// Moons category: the per-planet/dwarf bar chart replaces the notable-members
	// strip and members list this page deliberately omits.
	let moonCounts = $derived(cat.moons ? groupDetail?.global?.moon_counts : undefined);
	// Surface Features only: its type chips group by landform family.
	let featureFamilies = $derived(groupDetail?.global?.feature_families);
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
		// A failed load has no name to resolve — the alert panel speaks for it, and
		// warning "no name resolved" here would just be misleading.
		if (loading || loadError) return;
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
		// Opt-in: the two small-body categories say so in their config, and the
		// zones, flags and split-comet families through the category their
		// members belong to — none of them has a config entry.
		sphereLineup: () => cat.sphereLineup || groupDetail?.global?.applies_to === 'small_body',
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
	// Feature-type pages are entirely IAU gazetteer content, as is the Surface
	// Features browse node above them (`feature_type_count` marks it) — its
	// families, naming timeline and etymology all come from the gazetteer.
	let nomenclatureCredit = $derived(
		groupDetail?.global?.type === 'feature_type' || groupDetail?.global?.feature_type_count != null
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
					: cat.moons
						? m.tab_moons()
						: m.tab_members()
			: m.tab_moons()
	);
	let hasMembers = $derived(!!notableMembers && notableMembers.length > 0);
	// Tab only earns its place past the overview strip's capacity; ≤5 fit there.
	// Earth's Satellites strip sends "+N more" to the group, so no in-drawer tab.
	// Planet/dwarf lineups are their own complete member list, so they need none.
	let showMembersTab = $derived(
		hasMembers && !satellitesGroup && memberTotal > STRIP_CAPACITY && !cat.membersShownInFull
	);

	// Earth's satellites live on their own collection page rather than a tab here.
	let seeAllMembersHref = $derived(
		satellitesGroup
			? groupHref(appState, satellitesGroup, membersHeading)
			: tabHref(appState, 'members')
	);

	function seeAllMembers() {
		if (satellitesGroup) appState?.setGroup(satellitesGroup, membersHeading);
		else appState.setTab('members');
	}

	// A body's own IAU surface features. The strip is the top few; the tab holds
	// the full gazetteer for that body (Mars alone has ~2k).
	let notableFeatures = $derived(
		isGroupMode || isFeatureMode ? undefined : data?.global?.notable_features
	);
	let featureNames = $derived(data?.localized?.notable_feature_names);
	let featureTotal = $derived(data?.global?.feature_count ?? 0);
	let hasFeatures = $derived(!!notableFeatures && notableFeatures.length > 0);
	let showFeaturesTab = $derived(hasFeatures && featureTotal > STRIP_CAPACITY);

	// Pictures come in one shelf per subject: the object's own, its rings, and
	// the pooled shelves (its features, its moons, or a collection's members).
	// A pooled picture is labelled by its subject rather than its filename, so
	// the names the lists above already resolved are handed down.
	let gallerySubjectNames = $derived.by(() => {
		const names = new Map<string, string>();
		for (const member of notableMembers ?? []) {
			if (member.id) names.set(member.id, memberNames?.[member.id] ?? member.name);
		}
		for (const feature of notableFeatures ?? []) {
			const key = `${feature.id}:${feature.feature_id}`;
			names.set(String(feature.feature_id), featureNames?.[key] ?? feature.name);
		}
		return names;
	});
	let galleries = $derived(
		buildGalleries(
			(isGroupMode ? groupDetail?.global : data?.global) ?? undefined,
			displayName,
			(subject) => gallerySubjectNames.get(subject)
		)
	);
	// A `&gal=` naming no shelf here (a stale link, another object's member)
	// falls back to the index, and the viewer to the leading shelf.
	let activeGallery = $derived(findGallery(galleries, appState?.view.gallery ?? null));
	let hasImages = $derived(galleries.length > 0);
	let imageTotal = $derived(imageCount(galleries));
	let viewerImages = $derived((activeGallery ?? galleries[0])?.images);
	let viewerIndex = $derived(appState?.view.imageIndex);
	// Gate the viewer mount on a valid index AND a loaded images list. The
	// AppState's `?img=` URL parser doesn't know how many images this gallery
	// has, so we belt-and-braces the bound here too.
	let viewerActive = $derived(
		!!viewerImages &&
			viewerImages.length > 0 &&
			viewerIndex != null &&
			viewerIndex < viewerImages.length
	);

	function seeAllFeatures() {
		appState.setTab('features');
	}

	// The body cut open. Needs a layer model or a named atmosphere stack — the
	// ~30 bodies a mission actually constrained, not the 150,000 asteroids whose
	// interior is an estimate from a spectrum.
	let showStructureTab = $derived(
		!isGroupMode &&
			!isFeatureMode &&
			(!!data?.global?.interior?.layers?.length || !!data?.global?.atmosphere?.structure)
	);

	// The Structure tab's hero: the atmosphere shelf, since what a cross-section
	// abstracts is exactly what those pictures show — the cloud decks and storms
	// the profile below is a plot of. The interior has no such picture (its
	// articles illustrate with the same cutaway the tab already draws).
	let atmosphereGallery = $derived(findGallery(galleries, ATMOSPHERE_GALLERY));

	// The Surface tab's hero needs a map texture; the IAU chart grid is a bonus
	// only Mercury, Venus, Mars and the Moon carry.
	let showSurfaceHero = $derived(
		!isGroupMode && !isFeatureMode && hasFeatures && !!data?.global?.map_texture_available
	);
	let quadrangles = $state<Quadrangle[] | null>(null);
	$effect(() => {
		const id = isGroupMode || isFeatureMode ? null : body?.data.id;
		if (!id || !hasFeatures) {
			quadrangles = null;
			return;
		}
		let live = true;
		untrack(() => fetchBodyQuadrangles(id)).then((q) => {
			if (live) quadrangles = q;
		});
		return () => {
			live = false;
		};
	});
	// Only honoured while the hero is up, so a stale `&quad=` can't silently
	// filter the list on a body with no grid.
	let selectedQuad = $derived(
		quadrangles?.some((q) => q.code === appState.view.quad) ? appState.view.quad : null
	);
	let selectedQuadEntry = $derived(quadrangles?.find((q) => q.code === selectedQuad));
	let selectedQuadCount = $derived(selectedQuadEntry?.n);
	// Feature the list is hovering — the hero marks it on the map.
	let hoveredFeatureId = $state<number | null>(null);
	// Wikipedia intro for the picked chart. A quadrangle is a part of its body,
	// not a page of its own, so this is all there is to say about one; the
	// per-language file only loads once one is picked.
	let quadText = $state<QuadrangleText | null>(null);
	$effect(() => {
		const id = body?.data.id;
		const code = selectedQuad;
		const lang = getLocale();
		if (!id || !code) {
			quadText = null;
			return;
		}
		let live = true;
		untrack(() => fetchQuadrangleText(id, code, lang)).then((t) => {
			if (live) quadText = t;
		});
		return () => {
			live = false;
		};
	});

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

	// Named rings, gaps and ringlets — the eight ringed bodies only.
	let ringFeatures = $derived(isGroupMode ? undefined : data?.global?.ring_features);
	// Which object the host's moons hang off, for the chart's moon column: a
	// planet's are parented on the system barycentre, a minor planet's on the
	// body itself. Chariklo and friends orbit the Sun, whose children are the
	// whole small-body catalogue rather than a system.
	let ringMoonHostId = $derived(
		parentBody?.data.objectType === ObjectType.BARYCENTER ? parentBody.data.id : body?.data.id
	);
	let showRingsTab = $derived(Object.values(ringFeatures ?? {}).some((f) => !f.parent));
	let ringImages = $derived(isGroupMode ? undefined : data?.global?.ring_images);
	// Credits for the Rings tab alone: the catalogue's tables, plus whatever
	// prose and names this locale actually got.
	let ringCredits = $derived(
		(data?.global?.ring_sources ?? []).map((s) => ({ key: s.url, label: s.title, url: s.url }))
	);
	// Same tables on the Ring Systems collection page, where they back the mass
	// chart and the tiles rather than one body's catalogue.
	let groupRingCredits = $derived(
		(groupDetail?.global?.ring_sources ?? []).map((s) => ({
			key: s.url,
			label: s.title,
			url: s.url
		}))
	);
	let ringLocalized = $derived(Object.values(data?.localized?.ring_features ?? {}));
	let ringProseFromWikipedia = $derived(
		!!data?.localized?.ring_system?.extract || ringLocalized.some((f) => f.extract)
	);
	// Feature names come from Wikidata labels outside English, where the
	// catalogue's own names are used.
	let ringNamesLocalized = $derived(ringLocalized.some((f) => f.name));
	// The Structure tab's own credit: the two topic blurbs are the only licensed
	// text on it, and either one alone earns the CC BY-SA line.
	let structureProseFromWikipedia = $derived(
		!!data?.localized?.interior_page?.extract || !!data?.localized?.atmosphere_page?.extract
	);
	let showFragmentsTab = $derived(hasFragments && fragmentTotal > STRIP_CAPACITY);

	// Undo shadcn's flex-1: a tab is as wide as its label, so a full bar's slack
	// falls between the tabs instead of padding out the shortest one. h-full and
	// the raised underline keep the trigger and its indicator inside the list box:
	// the bar is a scroll container, which clips at its padding box, so shadcn's
	// default -5px underline would be cut off. The underline is inset by the
	// trigger's own padding so it underlines the label rather than the spacing
	// around it (! beats the variant's higher specificity).
	const TAB_TRIGGER_CLASS = 'px-2 flex-none h-full after:-bottom-1! after:start-2! after:end-2!';

	let tabPresent = $derived<Record<DrawerTab, boolean>>({
		overview: true,
		images: hasImages,
		features: showFeaturesTab,
		structure: showStructureTab,
		rings: showRingsTab,
		members: showMembersTab,
		fragments: showFragmentsTab
	});
	let tabCount = $derived(Object.values(tabPresent).filter(Boolean).length);

	// Shelves named after an aspect of this object rather than a subject of their
	// own: the tab that covers the same ground is where the rest of it is.
	const SHELF_TABS: Record<string, Exclude<DrawerTab, 'overview'>> = {
		rings: 'rings',
		atmosphere: 'structure',
		interior: 'structure',
		features: 'features',
		moons: 'members'
	};

	let tabLabels = $derived<Partial<Record<DrawerTab, string>>>({
		images: m.tab_images(),
		features: m.tab_features(),
		structure: m.tab_structure(),
		rings: m.tab_rings(),
		members: membersTabLabel,
		fragments: m.tab_fragments()
	});

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

	/** This page's own portrait, for a tile leading to another of its tabs. */
	let pageHero = $derived.by(() => {
		const image = (isGroupMode ? groupDetail?.global : data?.global)?.images?.[0];
		return image ? pickImageUrl(image, 300) : undefined;
	});

	// One promise per member, kept because the link resolves afresh on every
	// camera nudge (its href is built from the live view) and a new promise
	// restarts the tile's picture.
	const subjectHeroes = new Map<string, Promise<string | undefined>>();

	/** A member's portrait for its tile. The bundle fetch is cached, and asking
	 *  for it warms the page the tile leads to. */
	function subjectHero(id: string): Promise<string | undefined> {
		let hero = subjectHeroes.get(id);
		if (!hero) {
			hero = fetchObjectDetail(id).then((detail) => {
				const image = detail.global?.images?.[0];
				return image ? pickImageUrl(image, 300) : undefined;
			});
			subjectHeroes.set(id, hero);
		}
		return hero;
	}

	/** A picture's subject — an Object.id, or an IAU feature id on this body —
	 *  as a link to it. Features are numbered; objects carry a type prefix. */
	function subjectLink(subject: string | number): ShelfLink | undefined {
		const name = gallerySubjectNames.get(String(subject));
		if (!name) return undefined;
		if (typeof subject === 'number') {
			const bodyId = body?.data.id;
			if (!bodyId) return undefined;
			const focus = { bodyId, featureId: subject, featureName: name };
			return {
				label: name,
				kind: displayName,
				href: appState ? serializeUrl(applyFeature(appState.view, focus)) : undefined,
				open: () => focusFeature?.(bodyId, subject, name)
			};
		}
		// Its own pictures are what this link is about, so it lands on them
		// rather than on the object's overview.
		return {
			label: name,
			kind: m.tab_images(),
			hero: subjectHero(subject),
			href: focusHref(appState, subject, name, 'images'),
			open: () => focusObject?.(subject, name, { moveCamera: false, tab: 'images' })
		};
	}

	/** The destination tab's own drawing, where it has one for this shelf. */
	function shelfBackdrop(key: string): Snippet | undefined {
		if (key === RINGS_GALLERY) return ringStripId ? ringPlaneTile : undefined;
		if (key === ATMOSPHERE_GALLERY) return shelfAtmosphere ? atmosphereBandTile : undefined;
		if (key === MOONS_GALLERY) return moonDiscs.length ? moonDiscTile : undefined;
		if (key === FEATURES_GALLERY) return surfaceMapId ? surfaceMapTile : undefined;
		return undefined;
	}

	function shelfLink(gallery: Gallery): ShelfLink | undefined {
		if (gallery.subjectId) return subjectLink(gallery.subjectId);
		const tab = SHELF_TABS[gallery.key];
		if (!tab || !tabPresent[tab]) return undefined;
		// What the destination tab draws, rather than a photograph: every
		// photograph of the subject is already on the shelf underneath, and the
		// chart is what the tab has that the gallery doesn't.
		const drawn = shelfBackdrop(gallery.key);
		return {
			label: tabLabels[tab] ?? gallery.title,
			kind: displayName,
			hero: drawn ? undefined : pageHero,
			background: drawn,
			href: tabHref(appState, tab),
			open: () => appState.setTab(tab)
		};
	}

	// What the desktop bar holds before it crowds; past that it hands tabs over,
	// in this order, to whatever in the overview leads to them — the pill on the
	// hero image, for Images. A tab with no such way in can't be listed here.
	// (Coverage varies wildly per object, so this is a per-object budget, not a
	// fixed set: most objects never reach it and keep every tab in the bar.)
	const TAB_BUDGET = 4;
	const PROMOTABLE: readonly DrawerTab[] = ['images'];

	// Mobile scrolls its bar instead — the tabs stay where a thumb expects them.
	let promotedTabs = $derived.by(() => {
		const promoted = new Set<DrawerTab>();
		if (isMobile) return promoted;
		let inBar = tabCount;
		for (const tab of PROMOTABLE) {
			if (inBar <= TAB_BUDGET) break;
			if (!tabPresent[tab]) continue;
			promoted.add(tab);
			inBar--;
		}
		return promoted;
	});

	function seeAllFragments() {
		appState.setTab('fragments');
	}

	// Probe mission: the mission cross-ref tile lives in SatCrossRefs now; the
	// primary craft still shows a strip of its sibling craft below.
	let missionMembers = $derived(isGroupMode ? undefined : data?.global?.mission_members);
	let missionMemberNames = $derived(data?.localized?.mission_member_names);
	let missionMemberTotal = $derived(data?.global?.mission_member_count ?? 0);
	let hasMissionMembers = $derived(!!missionMembers && missionMembers.length > 0);

	let seeAllMissionMembersHref = $derived.by(() => {
		const link = data?.global?.mission;
		return link ? groupHref(appState, link.primary_id, link.name) : undefined;
	});

	function seeAllMissionMembers() {
		const link = data?.global?.mission;
		if (link) appState?.setGroup(link.primary_id, link.name);
	}

	// Overview member strips (same card UI, different sources): body moons/sats,
	// split-comet fragments, mission craft. Lineup/small-body/Solar-System/ring
	// pages route members through their own hero or tiles, so drop the plain strip.
	interface OverviewStrip {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
		totalCount: number;
		heading: string;
		seeAllHref?: string;
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
			!cat.ringSystems &&
			!isSmallBodyZone &&
			!cat.smallBody
		) {
			strips.push({
				members: notableMembers,
				localizedNames: memberNames,
				totalCount: memberTotal,
				heading: membersHeading,
				seeAllHref: seeAllMembersHref,
				onSeeAll: seeAllMembers
			});
		}
		// Surface features sit below the moons strip: same card UI, but focusing a
		// row flies to a point on this body rather than to another object.
		if (hasFeatures && notableFeatures) {
			strips.push({
				members: notableFeatures,
				localizedNames: featureNames,
				totalCount: featureTotal,
				heading: m.features_section(),
				seeAllHref: tabHref(appState, 'features'),
				onSeeAll: seeAllFeatures
			});
		}
		if (hasFragments && notableFragments) {
			strips.push({
				members: notableFragments,
				localizedNames: fragmentNames,
				totalCount: fragmentTotal,
				heading: m.fragments_section(),
				seeAllHref: tabHref(appState, 'fragments'),
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
				seeAllHref: seeAllMissionMembersHref,
				onSeeAll: seeAllMissionMembers
			});
		}
		return strips;
	});
	// URL-backed so it's deep-linkable. A tab whose content this object lacks
	// falls back to overview, never rendering empty.
	let activeTab = $derived<DrawerTab>(
		appState.view.tab && tabPresent[appState.view.tab] ? appState.view.tab : 'overview'
	);
	// A promoted tab drops the bar and takes the header instead: the object's name
	// moves into the crumb and the tab names the view. Still the same tab in the
	// URL — only the chrome around it differs.
	let soloTab = $derived<DrawerTab | null>(
		promotedTabs.has(activeTab) || activeGallery ? activeTab : null
	);
	let soloCrumb = $derived<Crumb | null>(
		activeGallery
			? { label: m.tab_images(), target: { kind: 'tab', tab: 'images' } }
			: soloTab
				? { label: displayName, target: { kind: 'tab', tab: 'overview' } }
				: null
	);
	let soloTitle = $derived(
		activeGallery ? activeGallery.title : soloTab === 'images' ? m.tab_images() : displayName
	);
	let barTabCount = $derived(tabCount - promotedTabs.size);

	/** A tab earns a place in the bar when the object has it and the bar kept it. */
	function inBar(tab: DrawerTab): boolean {
		return tabPresent[tab] && !promotedTabs.has(tab);
	}

	// What the URL is focused on, in `focusableKey` form. A tile that opens
	// another body on a specific tab (moon → planet's Moons, feature → host's
	// Features) rewrites the URL a beat before the renderer hands us the new
	// focusable; without this the scrub below would wipe the tab in that gap.
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

	// A deep link can land on a tab past the scrollable bar's edge; nudge the
	// bar until the trigger clears the px-4 edge inset. Instant on the
	// load-time run, animated on later switches. barTabCount re-runs this when
	// late-loading data reflows the bar under an unchanged active tab.
	let tabBarEl = $state<HTMLElement | null>(null);
	let tabBarSettled = false;
	$effect(() => {
		void activeTab;
		void barTabCount;
		const active = tabBarEl?.querySelector<HTMLElement>('[data-state="active"]');
		if (!tabBarEl || !active) return;
		const bar = tabBarEl.getBoundingClientRect();
		const trigger = active.getBoundingClientRect();
		const start = trigger.left - bar.left - 16;
		const end = trigger.right - bar.right + 16;
		const delta = start < 0 ? start : end > 0 ? end : 0;
		if (delta) tabBarEl.scrollBy({ left: delta, behavior: tabBarSettled ? 'smooth' : 'instant' });
		tabBarSettled = true;
	});
</script>

{#snippet tabsBar()}
	<!-- A lone Overview tab switches nothing, so the bar goes with it. Scrolls on
	     its own past the budget (mobile, which promotes nothing); without this the
	     whole drawer scrolls sideways. -->
	{#if barTabCount >= 2}
		<div
			bind:this={tabBarEl}
			class="pt-2 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
		>
			<!-- The list, not the scroll wrapper, carries the border and edge padding:
			     a scroll container's own end padding and border don't travel with
			     overflowing content, which left the last tab flush against the screen
			     edge and the underline clipped. min-w-max keeps every tab inside the
			     list box when the bar overflows.
			     Trigger padding is spacing between tabs, so the outer two drop theirs,
			     and the matching underline inset with it, to sit flush with the
			     drawer's own edge. -->
			<Tabs.List
				variant="line"
				class={[
					'w-full min-w-max border-b px-4',
					'[&>*:first-child]:ps-0 [&>*:first-child]:after:start-0! [&>*:last-child]:pe-0 [&>*:last-child]:after:end-0!',
					// Only a full desktop bar spreads; anywhere else the list is wider
					// than its tabs (w-full slack, or mobile's scroll room), and the
					// variant's justify-center would float them mid-bar.
					!isMobile && barTabCount >= 4 ? 'justify-between' : 'justify-start gap-2'
				]}
			>
				<Tabs.Trigger value="overview" class={TAB_TRIGGER_CLASS}>{m.tab_overview()}</Tabs.Trigger>
				{#if inBar('images')}
					<Tabs.Trigger value="images" class={TAB_TRIGGER_CLASS}>
						{m.tab_images()}
						<Badge variant="secondary" class="text-[10px] py-0 px-1.5 h-4 leading-none">
							{imageTotal}
						</Badge>
					</Tabs.Trigger>
				{/if}
				{#if inBar('features')}
					<!-- No count: five figures of nomenclature is the widest badge the bar
					     can be handed, and the list under it opens on the total anyway. -->
					<Tabs.Trigger value="features" class={TAB_TRIGGER_CLASS}>
						{m.tab_features()}
					</Tabs.Trigger>
				{/if}
				{#if inBar('structure')}
					<Tabs.Trigger value="structure" class={TAB_TRIGGER_CLASS}>
						{m.tab_structure()}
					</Tabs.Trigger>
				{/if}
				{#if inBar('rings')}
					<!-- No count: the ring bar is the widest, and the chart states it. -->
					<Tabs.Trigger value="rings" class={TAB_TRIGGER_CLASS}>{m.tab_rings()}</Tabs.Trigger>
				{/if}
				{#if inBar('members')}
					<Tabs.Trigger value="members" class={TAB_TRIGGER_CLASS}>
						{membersTabLabel}
						<Badge variant="secondary" class="text-[10px] py-0 px-1.5 h-4 leading-none">
							{formatCompactNumber(memberTotal)}
						</Badge>
					</Tabs.Trigger>
				{/if}
				{#if inBar('fragments')}
					<Tabs.Trigger value="fragments" class={TAB_TRIGGER_CLASS}>
						{m.tab_fragments()}
						<Badge variant="secondary" class="text-[10px] py-0 px-1.5 h-4 leading-none">
							{formatCompactNumber(fragmentTotal)}
						</Badge>
					</Tabs.Trigger>
				{/if}
			</Tabs.List>
		</div>
	{/if}
{/snippet}

<!-- The active tab's hero sits above the (single) tablist, so the tabs read as
     sub-navigation under the object's hero rather than pinned to the top. -->
{#snippet activeHero()}
	{#if activeTab === 'overview'}
		{#if loading}
			<div class="flex flex-col gap-4 px-4 pt-1 pb-3" aria-hidden="true">
				<Skeleton class="w-full h-36 rounded-md" />
				<Skeleton class="w-3/4 h-6" />
				<Skeleton class="w-1/2 h-4" />
			</div>
		{:else if !loadError}
			<div class="px-4 pt-1 pb-3">
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
					galleryHref={imageHref(appState, 0, MAIN_GALLERY)}
					onShowGallery={() => appState.setImage(0, MAIN_GALLERY)}
					listHref={tabHref(appState, 'images')}
					onShowList={() => appState.setTab('images')}
					imageCount={imageTotal}
				/>
			</div>
		{/if}
	{:else if activeTab === 'features'}
		<!-- The quadrangle map is this tab's hero: picking a chart filters the
		     list below it. -->
		{#if body && showSurfaceHero}
			<div class="px-4 pt-1 pb-3">
				<SurfaceHero
					bodyId={body.data.id}
					quads={quadrangles ?? []}
					selected={selectedQuad}
					onselect={(code) => appState.setQuad(code)}
					markedFeatureId={hoveredFeatureId}
				/>
			</div>
		{/if}
	{:else if activeTab === 'rings'}
		<!-- One picture of the system, above the chart that anatomises it. -->
		{#if ringImages?.length}
			<div class="px-4 pt-1 pb-3">
				<GalleryHero
					images={ringImages}
					alt={data?.localized?.ring_system?.name ?? m.tab_rings()}
					gallery={RINGS_GALLERY}
				/>
			</div>
		{/if}
	{:else if activeTab === 'structure'}
		<!-- The atmosphere as photographed, above the same atmosphere as a profile. -->
		{#if atmosphereGallery}
			<div class="px-4 pt-1 pb-3">
				<GalleryHero
					images={atmosphereGallery.images}
					alt={m.atmosphere()}
					gallery={ATMOSPHERE_GALLERY}
				/>
			</div>
		{/if}
	{:else if activeTab === 'members'}
		<!-- The lineup is this tab's hero; its imagery/size credits ride at the
		     foot of the panel, where the spheres render. -->
		{#if lineup.isMoonLineup}
			<div class="px-4 pt-1 pb-3">{@render lineupHeroSnippet()}</div>
		{/if}
		<!-- Solar System: the minimap is the page hero, so the sphere lineup lives
		     here (paginated). -->
		{#if lineup.solarSystemLineup}
			<div class="px-4 pt-1 pb-3">
				<BodyLineup
					bodies={lineup.solarSystemLineup.bodies}
					ariaLabel={fallbackName}
					perPage={lineup.solarSystemLineup.perPage}
				/>
			</div>
		{/if}
	{/if}
{/snippet}

{#snippet ringPlaneTile()}
	<RingStripBar bodyId={ringStripId ?? ''} />
{/snippet}

{#snippet atmosphereBandTile()}
	{#if shelfAtmosphere}
		<AtmosphereBandBar atmosphere={shelfAtmosphere} />
	{/if}
{/snippet}

{#snippet moonDiscTile()}
	<MoonDiscRow bodies={moonDiscs} />
{/snippet}

{#snippet surfaceMapTile()}
	<SurfaceMapBar bodyId={surfaceMapId ?? ''} />
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
	{#if loadError}
		<div role="alert" class="flex flex-col items-center gap-3 px-4 py-16 text-center">
			<p class="text-sm font-medium text-foreground">{m.detail_error_title()}</p>
			<p class="max-w-xs text-xs text-muted-foreground">{m.detail_error_body()}</p>
			<Button variant="secondary" size="sm" onclick={retryLoad}>{m.retry()}</Button>
		</div>
	{:else if loading}
		<div class="flex flex-col gap-4 p-1">
			<Skeleton class="w-full h-20" />
			<Skeleton class="w-full h-32" />
		</div>
	{:else}
		<div class="flex flex-col gap-5 p-1">
			{#if isGroupMode && groupDetail?.global}
				<GroupStatCards global={groupDetail.global} />
			{:else if feature}
				<FeatureStatCards {feature} detail={featureDetail} />
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
			{#if isFeatureMode && body}
				<FeatureGroupLinks
					hostId={body.data.id}
					hostName={body.data.name ?? undefined}
					typeSlug={featureType?.slug}
					typeLabel={featureType?.label}
				/>
			{:else if isPlanetBody}
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
					seeAllHref={strip.seeAllHref}
					onSeeAll={strip.onSeeAll}
					focusMovesCamera={strip.focusMovesCamera ?? true}
				/>
			{/each}
			{#if feature}
				<FeatureProperties
					{feature}
					detail={featureDetail}
					hostId={body?.data.id}
					hostName={body?.data.name ?? undefined}
				/>
			{:else if body}
				<Bulk global={data?.global ?? null} />
				<Atmosphere global={data?.global ?? null} />
				<Interior global={data?.global ?? null} />
				<Rings global={data?.global ?? null} {body} />
				<Brightness global={data?.global ?? null} />
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
				{#if cat.ringSystems && notableMembers && notableMembers.length > 0}
					<RingSystemTiles members={notableMembers} localizedNames={memberNames} />
					<RingMassChart members={notableMembers} localizedNames={memberNames} />
				{/if}
				{#if cat.planets && notableMembers && notableMembers.length > 0}
					<PlanetMassChart members={notableMembers} localizedNames={memberNames} />
				{/if}
				{#if cat.solarSystem}
					<SolarSystemMassChart />
				{/if}
				{#if moonCounts && moonCounts.length > 0}
					<CountPerBodyChart
						entries={moonCounts}
						title={m.group_moons_per_planet()}
						tab="members"
					/>
				{/if}
				{#if categoryPlot && groupDetail?.global}
					<GroupOrbitMap global={groupDetail.global} plotOverride={categoryPlot} />
				{/if}
				{#if visibleChildGroups.length && !cat.solarSystem}
					<!-- Surface Features groups its 57 type chips by landform family. -->
					{#if featureFamilies}
						<FeatureTypeFamilies families={featureFamilies} childGroups={visibleChildGroups} />
					{:else}
						<ChildGroups childGroups={visibleChildGroups} />
					{/if}
				{/if}
				<GroupProperties
					global={groupDetail?.global ?? null}
					localized={groupDetail?.localized ?? null}
				/>
			{/if}
			<ObjectLinks global={data?.global ?? null} localized={data?.localized ?? null} />
			<SourcesFooter
				global={data?.global ?? null}
				rings={groupRingCredits}
				earthSat={earthSatCredit}
				nomenclature={nomenclatureCredit}
				wikipediaLicensed={!!data?.localized?.wikipedia?.extract}
				pck={lineup.overviewCredits.pck}
				lightcurvePole={lineup.overviewCredits.lightcurvePole}
				sbdb={lineup.overviewCredits.sbdb}
				wikidata={lineup.overviewCredits.wikidata}
				imagery={lineup.overviewCredits.imagery}
			/>
		</div>
	{/if}
{/snippet}

{#snippet imagesPanel()}
	<ImagesPanel
		{galleries}
		active={activeGallery}
		alt={displayName}
		subjectName={(subject) => gallerySubjectNames.get(subject)}
		{shelfLink}
		titles={isGroupMode ? groupDetail?.localized?.image_titles : data?.localized?.image_titles}
	/>
{/snippet}

{#snippet membersPanel()}
	<div class="flex flex-col gap-3 p-1">
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
			<SourcesFooter
				global={null}
				pck={lineup.pck}
				lightcurvePole={lineup.lightcurvePole}
				imagery={lineup.imagery}
			/>
		{/if}
	</div>
{/snippet}

{#snippet featuresPanel()}
	<div class="flex flex-col gap-3 p-1">
		{#if quadText}
			<ObjectDescription
				extract={quadText.extract}
				wikipediaUrl={quadText.url}
				truncateLength={200}
			/>
		{/if}
		{#if body && hasFeatures}
			<FeatureTypeFilter
				bodyId={body.data.id}
				quad={selectedQuad}
				selected={appState.view.featureType}
				onselect={(code) => appState.setFeatureType(code)}
			/>
			{@const narrowed = selectedQuad != null || appState.view.featureType != null}
			<PaginatedMemberList
				source={{
					kind: 'features',
					bodyId: body.data.id,
					quad: selectedQuad ?? undefined,
					featureType: appState.view.featureType ?? undefined
				}}
				totalCount={selectedQuad ? (selectedQuadCount ?? 0) : featureTotal}
				localizedNames={featureNames}
				fallback={narrowed ? [] : (notableFeatures ?? [])}
				onHoverFeature={(id) => (hoveredFeatureId = id)}
			/>
		{/if}
	</div>
{/snippet}

{#snippet ringsPanel()}
	<div class="flex flex-col gap-3 p-1">
		{#if ringFeatures}
			<!-- System-wide, so it sits above the chart rather than inside it:
			     these three do not change as you drill into a ring. -->
			<RingStatCards stats={data?.global?.ring_stats} />
			<RingCatalog
				features={ringFeatures}
				localized={data?.localized?.ring_features}
				system={data?.localized?.ring_system}
				bodyRadiusKm={data?.global?.radii?.a}
				bodyId={body?.data.id}
				systemId={ringMoonHostId}
				{clock}
			/>
			<!-- The way back out to the other ringed bodies: this tab is where a
			     visitor finds out there are rings to compare. -->
			<BodyCategoryTile slug={CAT_RING_SYSTEMS} />
			<SourcesFooter
				global={null}
				rings={ringCredits}
				wikidata={ringNamesLocalized}
				wikipediaLicensed={ringProseFromWikipedia}
			/>
		{/if}
	</div>
{/snippet}

{#snippet fragmentsPanel()}
	<div class="flex flex-col gap-3 p-1">
		{#if notableFragments && notableFragments.length > 0}
			<MemberList
				members={notableFragments}
				localizedNames={fragmentNames}
				focusMovesCamera={false}
			/>
		{/if}
	</div>
{/snippet}

{#snippet structurePanel()}
	<div class="flex flex-col gap-5 p-1">
		<!-- Above both sections rather than inside either: mass belongs to the
		     interior, pressure to the atmosphere, and the third slot to whichever
		     of the two this body has anything to say about. -->
		<StructureStatCards global={data?.global ?? null} />
		<Structure global={data?.global ?? null} localized={data?.localized ?? null} />
		<SourcesFooter global={data?.global ?? null} wikipediaLicensed={structureProseFromWikipedia} />
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

<!-- A promoted tab's panel, rendered outside Tabs.Root: with no trigger left in
     the bar there is nothing for a tabpanel to be labelled by, so it stops being
     one and becomes the drawer's only content. -->
{#snippet soloPanel(contentClass: string)}
	<div class={contentClass}>
		{#if soloTab === 'images'}
			{@render imagesPanel()}
		{/if}
	</div>
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
	<Tabs.Content value="features" class={contentClass}>
		{@render featuresPanel()}
	</Tabs.Content>
	<Tabs.Content value="rings" class={contentClass}>
		{@render ringsPanel()}
	</Tabs.Content>
	<Tabs.Content value="structure" class={contentClass}>
		{@render structurePanel()}
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
				{inert}
				trapFocus={false}
				aria-labelledby="detail-drawer-title"
				class="fixed inset-x-0 bottom-0 z-50 flex h-dvh max-h-dvh flex-col rounded-t-xl border-t bg-background shadow-lg outline-none"
			>
				<div bind:this={headerEl} class="flex flex-col items-center gap-2 px-4 pt-3 pb-2">
					<div class="h-1 w-10 rounded-full bg-muted-foreground/40"></div>
					<div class="flex w-full items-center justify-between gap-2">
						<DrawerTitle {crumb} title={displayName} id="detail-drawer-title" />
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
						class="flex-1 min-h-0 {isAtTop ? 'overflow-y-auto' : 'overflow-hidden'}"
						style="padding-bottom: calc(1rem + {TOP_GAP_PX}px + var(--safe-bottom));"
					>
						{@render activeHero()}
						{@render tabsBar()}
						{@render tabPanels('px-4 pt-4')}
					</div>
				</Tabs.Root>
			</Vaul.Content>
		</Vaul.Portal>
	</Vaul.Root>
{:else}
	<!-- Desktop: side panel -->
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

<!-- Mounted as a sibling of the drawer/aside, not a descendant: keeps the
     viewer's lifecycle and pointer events out of Vaul's drag detection and
     out of the drawer's CSS transform context. PhotoSwipe additionally
     appends its own DOM to document.body. -->
{#if viewerActive && viewerImages}
	<ImageViewer
		images={viewerImages}
		alt={displayName}
		subjectLink={(image) => (image.subject === undefined ? undefined : subjectLink(image.subject))}
	/>
{/if}
