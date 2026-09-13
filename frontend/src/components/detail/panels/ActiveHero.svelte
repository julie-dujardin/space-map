<script lang="ts">
	// The active tab's hero, rendered above the tab bar in both frames, so the
	// tabs read as sub-navigation under it.
	import { getContext, type Snippet } from 'svelte';
	import HeroSkeleton from '../frame/skeleton/HeroSkeleton.svelte';
	import ObjectHeader from '../frame/ObjectHeader.svelte';
	import SurfaceHero from '../sections/SurfaceHero.svelte';
	import PanoramaMinimap from '../../panorama/PanoramaMinimap.svelte';
	import GalleryHero from '../sections/GalleryHero.svelte';
	import BodyLineup from '../charts/BodyLineup.svelte';
	import SolarSystemMap from '../charts/SolarSystemMap.svelte';
	import PlanetarySystemMap from '../charts/PlanetarySystemMap.svelte';
	import { groupTypeLabel, organizationRoleLabel, satelliteCategoryLabel } from '$lib/format/group';
	import { ATMOSPHERE_GALLERY, MAIN_GALLERY, RINGS_GALLERY } from '$lib/fetch/objects/galleries';
	import { imageHref, tabHref } from '$lib/state/focus-link';
	import type { CategoryConfig } from '$lib/state/category-config';
	import type { PositionedBody } from '$lib/types/objects';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { DrawerTab } from '$lib/state/view';
	import type { DetailLoad } from '../state/detail-load.svelte';
	import type { GalleryState } from '../state/gallery-state.svelte';
	import type { SurfaceState } from '../state/surface-state.svelte';
	import type { TraverseState } from '../state/traverse-state.svelte';
	import type { MembersState } from '../state/members-state.svelte';
	import type { LineupHero } from '../charts/lineup-hero.svelte';
	import type { PlanetarySystemState } from '../charts/planetary-system.svelte';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		body: PositionedBody | null;
		cat: CategoryConfig;
		fallbackName: string;
		activeTab: DrawerTab;
		load: DetailLoad;
		gallery: GalleryState;
		surface: SurfaceState;
		traverse: TraverseState;
		members: MembersState;
		lineup: LineupHero;
		planetarySystem: PlanetarySystemState;
	}

	let {
		body,
		cat,
		fallbackName,
		activeTab,
		load,
		gallery,
		surface,
		traverse,
		members,
		lineup,
		planetarySystem
	}: Props = $props();

	const appState = getContext<AppState>('appState');

	let data = $derived(load.data);
	let ringImages = $derived(data?.global?.ring_images);
	let groupHeaderBadges = $derived.by(() => {
		const g = load.groupDetail?.global;
		if (!g) return undefined;
		const out: string[] = [groupTypeLabel(g.type)];
		for (const role of g.roles ?? []) out.push(organizationRoleLabel(role));
		for (const c of g.categories ?? []) out.push(satelliteCategoryLabel(c));
		return out;
	});

	// One hero per tab, keyed so a new tab has to say whether it has one.
	// Undefined where this object gives the tab nothing to draw. Overview's
	// loading skeleton stands outside the table: it replaces the hero rather
	// than being one.
	let heroes = $derived<Record<DrawerTab, Snippet | undefined>>({
		overview: load.loadError ? undefined : objectHeaderHero,
		targets: undefined,
		traverse: traverse.traverse ? traverseHero : undefined,
		images: undefined,
		features: body && surface.showSurfaceHero ? surfaceQuadHero : undefined,
		structure: gallery.atmosphereGallery ? atmosphereHero : undefined,
		rings: ringImages?.length ? ringGalleryHero : undefined,
		members: lineup.isMoonLineup
			? lineupHeroSnippet
			: lineup.membersLineup
				? membersLineupHero
				: undefined,
		fragments: undefined,
		probes: lineup.probeLineup ? probeLineupHero : undefined
	});
	let hero = $derived(heroes[activeTab]);
</script>

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
	<SolarSystemMap ariaLabel={fallbackName} localizedNames={members.memberNames} />
{/snippet}

{#snippet planetarySystemMapSnippet()}
	{#if planetarySystem.isSystemPage && planetarySystem.system}
		<PlanetarySystemMap system={planetarySystem.system} ariaLabel={fallbackName} />
	{/if}
{/snippet}

{#snippet objectHeaderHero()}
	<ObjectHeader
		global={data?.global ?? null}
		localized={data?.localized ?? null}
		{fallbackName}
		leadingBadges={groupHeaderBadges ??
			(planetarySystem.isSystemPage ? [m.satellite_system_badge()] : undefined)}
		hero={cat.solarSystem
			? solarSystemMapSnippet
			: planetarySystem.isSystemPage && planetarySystem.system
				? planetarySystemMapSnippet
				: lineup.hero && !lineup.isMoonLineup
					? lineupHeroSnippet
					: undefined}
		galleryHref={imageHref(appState, 0, MAIN_GALLERY)}
		onShowGallery={() => appState.setImage(0, MAIN_GALLERY)}
		listHref={tabHref(appState, 'images')}
		onShowList={() => appState.setTab('images')}
		imageCount={gallery.imageTotal}
	/>
{/snippet}

<!-- The whole ground track on a map of the body, above the panoramas picked
     off it. No marker: the tab is the traverse, not a place on it. -->
{#snippet traverseHero()}
	{#if traverse.traverse}
		<div class="relative aspect-[16/9] w-full overflow-hidden rounded-lg">
			<PanoramaMinimap
				fill
				bodyId={traverse.traverse.bodyId}
				entries={traverse.traverse.entries}
				radiusKm={traverse.traverse.radiusKm}
			/>
		</div>
	{/if}
{/snippet}

<!-- The quadrangle map is the Features tab's hero: picking a chart filters the
     list below it. -->
{#snippet surfaceQuadHero()}
	{#if body}
		<SurfaceHero
			bodyId={body.data.id}
			quads={surface.quadrangles ?? []}
			selected={surface.selectedQuad}
			onselect={(code) => appState.setQuad(code)}
			markedFeatureId={surface.hoveredFeatureId}
		/>
	{/if}
{/snippet}

<!-- One picture of the ring system, above the chart that anatomises it. -->
{#snippet ringGalleryHero()}
	{#if ringImages?.length}
		<GalleryHero
			images={ringImages}
			alt={data?.localized?.ring_system?.name ?? m.tab_rings()}
			gallery={RINGS_GALLERY}
		/>
	{/if}
{/snippet}

<!-- The atmosphere as photographed, above the same atmosphere as a profile. -->
{#snippet atmosphereHero()}
	{#if gallery.atmosphereGallery}
		<GalleryHero
			images={gallery.atmosphereGallery.images}
			alt={m.atmosphere()}
			gallery={ATMOSPHERE_GALLERY}
		/>
	{/if}
{/snippet}

<!-- The craft that went there, to scale against each other, above the list
     that dates each visit. -->
{#snippet probeLineupHero()}
	{#if lineup.probeLineup}
		<BodyLineup
			bodies={lineup.probeLineup.bodies}
			ariaLabel={lineup.probeLineup.ariaLabel}
			perPage={lineup.probeLineup.perPage}
		/>
	{/if}
{/snippet}

<!-- The members drawn to scale, above the list that names them. Its
     imagery/size credits ride at the foot of the panel, where they render. -->
{#snippet membersLineupHero()}
	{#if lineup.membersLineup}
		<BodyLineup
			bodies={lineup.membersLineup.bodies}
			ariaLabel={lineup.membersLineup.ariaLabel}
			perPage={lineup.membersLineup.perPage}
		/>
	{/if}
{/snippet}

{#if activeTab === 'overview' && load.loading}
	<HeroSkeleton />
{:else if hero}
	<div class="px-4 pt-1 pb-3">{@render hero()}</div>
{/if}
