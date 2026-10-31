<script lang="ts">
	import { getContext, untrack } from 'svelte';
	import FragmentOf from '../../sections/FragmentOf.svelte';
	import FeatureGroupLinks from '../../sections/crossref/FeatureGroupLinks.svelte';
	import PlanetGroupLinks from '../../sections/crossref/PlanetGroupLinks.svelte';
	import DwarfPlanetGroupLinks from '../../sections/crossref/DwarfPlanetGroupLinks.svelte';
	import MoonGroupLinks from '../../sections/crossref/MoonGroupLinks.svelte';
	import BodyCategoryTile from '../../sections/crossref/BodyCategoryTile.svelte';
	import SmallBodyGroupLinks from '../../sections/crossref/SmallBodyGroupLinks.svelte';
	import SystemGroupLinks from '../../sections/crossref/SystemGroupLinks.svelte';
	import { STRIP_CAPACITY } from '../../members/MemberStrip.svelte';
	import SatCrossRefs from '../../sections/SatCrossRefs.svelte';
	import FamilyTile from '../../sections/crossref/FamilyTile.svelte';
	import { fetchExtrasolarMetadata, type ExtrasolarMetadata } from '$lib/fetch/extrasolar/files';
	import { familiesOf, familyLinks, type FamilyLink } from '$lib/fetch/extrasolar/families';
	import type { ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
	import type { Planet } from '$lib/fetch/extrasolar/planets';
	import { isStarSystem } from '$lib/fetch/extrasolar/systems';
	import {
		CAT_CONSTELLATIONS,
		CAT_SOLAR_SYSTEM,
		STAR_FAMILY_SLUG_PREFIX
	} from '$lib/fetch/groups/registry';
	import { ObjectType, type OrbitalElements, type PositionedBody } from '$lib/types/objects';
	import { moonHost } from '$lib/state/breadcrumb';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { ObjectDetailData } from '$lib/fetch/objects/object-data';
	import type { MembersState } from '../../state/members-state.svelte';
	import type { PlanetarySystemState } from '../../charts/planetary-system.svelte';
	import type { Focusable } from '$lib/state/focusable';

	type FocusedFeature = Extract<Focusable, { kind: 'feature' }>['feature'];

	interface Props {
		body: PositionedBody | null;
		feature: FocusedFeature | null;
		featureType: { slug: string; label: string } | null;
		data: ObjectDetailData | null;
		members: MembersState;
		orbitElements: OrbitalElements | undefined;
		planetarySystem: PlanetarySystemState;
		/** The records of an extrasolar star. */
		star: ExtrasolarRecord | null;
		/** The record of an extrasolar planet. */
		planet: Planet | null;
	}

	let {
		body,
		feature,
		featureType,
		data,
		members,
		orbitElements,
		planetarySystem,
		star,
		planet
	}: Props = $props();

	const ctx = getContext<ContextManager>('ctx');

	let fragmentOf = $derived(members.fragmentOf);
	// Small body → its SBDB orbit-class group. Suppressed on fragments: they
	// point to their parent comet instead
	let orbitClass = $derived(fragmentOf ? undefined : data?.global?.sbdb?.class);
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
	// A moon's host (the planet, past the barycenter) for its tile.
	let moonParent = $derived(
		isMoonBody && body ? moonHost(ctx, body.data.parentId, data) : undefined
	);
	let isStarBody = $derived(body?.data.objectType === ObjectType.STAR);
	// A planetary barycenter stands for its whole system, so it cross-refs the
	// primary and the moon list rather than the barycenter's own (empty) pages.
	let system = $derived(planetarySystem.isSystemPage ? planetarySystem.system : null);

	// A star's or a planet's most specific families. Two tiles at most, as
	// three in a row look uneven; the Sun's Solar System tile takes one of them.
	let sunLinks = $derived(
		(isStarBody ? (data?.global?.star_families ?? []) : []).slice(0, 1).map(
			(family): FamilyLink => ({
				type: 'star_family',
				slug: `${STAR_FAMILY_SLUG_PREFIX}${family}`,
				estimated: false
			})
		)
	);
	let familyTiles = $state.raw<FamilyLink[]>([]);
	let isStarPage = $derived(!!star);
	$effect(() => {
		const row = star && !isStarSystem(star) ? star.metadata : null;
		const record = planet;
		familyTiles = [];
		const linksOf = row
			? (meta: ExtrasolarMetadata | null) => {
					const families = meta?.families ?? [];
					return familyLinks(
						'star_family',
						familiesOf(row.families, families),
						familiesOf(row.familiesEstimated, families),
						families
					);
				}
			: record
				? (meta: ExtrasolarMetadata | null) =>
						familyLinks(
							'planet_family',
							record.families,
							record.families_estimated,
							meta?.planets?.families ?? []
						)
				: null;
		if (!linksOf) return;
		let current = true;
		untrack(fetchExtrasolarMetadata).then(
			(meta) => {
				if (current) familyTiles = linksOf(meta).slice(0, 2);
			},
			(e: unknown) => console.warn('[families] no export metadata:', e)
		);
		return () => {
			current = false;
		};
	});
</script>

{#if fragmentOf}
	<FragmentOf {fragmentOf} />
{/if}
{#if feature && body}
	<FeatureGroupLinks
		hostId={body.data.id}
		hostName={body.data.name ?? undefined}
		typeSlug={featureType?.slug}
		typeLabel={featureType?.label}
	/>
{:else if isPlanetBody}
	<PlanetGroupLinks
		families={data?.global?.planet_families}
		systemId={planetarySystem.systemId ?? undefined}
		system={planetarySystem.system ?? undefined}
		systemName={planetarySystem.systemName}
	/>
{:else if isDwarfPlanetBody}
	<DwarfPlanetGroupLinks
		{orbitClass}
		systemId={planetarySystem.systemId ?? undefined}
		system={planetarySystem.system ?? undefined}
		systemName={planetarySystem.systemName}
	/>
{:else if isMoonBody}
	<MoonGroupLinks
		parentId={moonParent?.id}
		parentName={moonParent?.name}
		systemId={planetarySystem.systemId ?? undefined}
		system={planetarySystem.system ?? undefined}
		systemName={planetarySystem.systemName}
	/>
{:else if system}
	<SystemGroupLinks
		primaryId={system.planet.data.id}
		primaryName={system.planetName}
		hasMoons={system.moonCount > STRIP_CAPACITY}
		moonDiscs={system.moonDiscs}
		hasRings={system.hasRingCatalog}
	/>
{:else if isStarBody}
	<div class="grid grid-cols-2 gap-2">
		<BodyCategoryTile slug={CAT_SOLAR_SYSTEM} class={sunLinks.length ? '' : 'col-span-2'} />
		{#each sunLinks as link (link.slug)}
			<FamilyTile {link} />
		{/each}
	</div>
{:else if familyTiles.length || isStarPage}
	<div class="grid grid-cols-2 gap-2">
		{#each familyTiles as link (link.slug)}
			<FamilyTile {link} class={familyTiles.length === 1 && !isStarPage ? 'col-span-2' : ''} />
		{/each}
		{#if isStarPage}
			<BodyCategoryTile
				slug={CAT_CONSTELLATIONS}
				class={familyTiles.length === 1 ? '' : 'col-span-2'}
			/>
		{/if}
	</div>
{:else if orbitClass}
	<SmallBodyGroupLinks {orbitClass} flag={smallBodyFlag} />
{/if}
{#if body}
	<SatCrossRefs
		global={data?.global ?? null}
		localized={data?.localized ?? null}
		{orbitElements}
		{body}
	/>
{/if}
