<script lang="ts">
	// The active tab's hero, rendered above the tab bar in both frames, so the
	// tabs read as sub-navigation under it.
	import { getContext } from 'svelte';
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import ObjectHeader from '../frame/ObjectHeader.svelte';
	import SurfaceHero from '../sections/SurfaceHero.svelte';
	import GalleryHero from '../sections/GalleryHero.svelte';
	import BodyLineup from '../charts/BodyLineup.svelte';
	import SolarSystemMap from '../charts/SolarSystemMap.svelte';
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
	import type { MembersState } from '../state/members-state.svelte';
	import type { LineupHero } from '../charts/lineup-hero.svelte';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		body: PositionedBody | null;
		cat: CategoryConfig;
		fallbackName: string;
		activeTab: DrawerTab;
		load: DetailLoad;
		gallery: GalleryState;
		surface: SurfaceState;
		members: MembersState;
		lineup: LineupHero;
	}

	let { body, cat, fallbackName, activeTab, load, gallery, surface, members, lineup }: Props =
		$props();

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

{#if activeTab === 'overview'}
	{#if load.loading}
		<div class="flex flex-col gap-4 px-4 pt-1 pb-3" aria-hidden="true">
			<Skeleton class="w-full h-36 rounded-md" />
			<Skeleton class="w-3/4 h-6" />
			<Skeleton class="w-1/2 h-4" />
		</div>
	{:else if !load.loadError}
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
				imageCount={gallery.imageTotal}
			/>
		</div>
	{/if}
{:else if activeTab === 'features'}
	<!-- The quadrangle map is this tab's hero: picking a chart filters the
	     list below it. -->
	{#if body && surface.showSurfaceHero}
		<div class="px-4 pt-1 pb-3">
			<SurfaceHero
				bodyId={body.data.id}
				quads={surface.quadrangles ?? []}
				selected={surface.selectedQuad}
				onselect={(code) => appState.setQuad(code)}
				markedFeatureId={surface.hoveredFeatureId}
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
	{#if gallery.atmosphereGallery}
		<div class="px-4 pt-1 pb-3">
			<GalleryHero
				images={gallery.atmosphereGallery.images}
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
