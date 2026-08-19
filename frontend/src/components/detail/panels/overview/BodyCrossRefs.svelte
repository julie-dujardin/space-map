<script lang="ts">
	import { getContext } from 'svelte';
	import FragmentOf from '../../sections/FragmentOf.svelte';
	import FeatureGroupLinks from '../../sections/crossref/FeatureGroupLinks.svelte';
	import PlanetGroupLinks from '../../sections/crossref/PlanetGroupLinks.svelte';
	import DwarfPlanetGroupLinks from '../../sections/crossref/DwarfPlanetGroupLinks.svelte';
	import MoonGroupLinks from '../../sections/crossref/MoonGroupLinks.svelte';
	import BodyCategoryTile from '../../sections/crossref/BodyCategoryTile.svelte';
	import SmallBodyGroupLinks from '../../sections/crossref/SmallBodyGroupLinks.svelte';
	import SatCrossRefs from '../../sections/SatCrossRefs.svelte';
	import { CAT_SOLAR_SYSTEM } from '$lib/fetch/groups/registry';
	import { ObjectType, type OrbitalElements, type PositionedBody } from '$lib/types/objects';
	import { parentPlanet } from '$lib/state/breadcrumb';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { ObjectDetailData } from '$lib/fetch/objects/object-data';
	import type { MembersState } from '../../state/members-state.svelte';
	import type { Focusable } from '$lib/state/focusable';

	type FocusedFeature = Extract<Focusable, { kind: 'feature' }>['feature'];

	interface Props {
		body: PositionedBody | null;
		feature: FocusedFeature | null;
		featureType: { slug: string; label: string } | null;
		data: ObjectDetailData | null;
		members: MembersState;
		orbitElements: OrbitalElements | undefined;
		jd: number;
	}

	let { body, feature, featureType, data, members, orbitElements, jd }: Props = $props();

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
	// A moon's host planet (resolved past the nameless barycenter) for its tile.
	let moonParent = $derived(isMoonBody && body ? parentPlanet(ctx, body.data.parentId) : undefined);
	let isStarBody = $derived(body?.data.objectType === ObjectType.STAR);
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
		{orbitElements}
		{body}
		{jd}
	/>
{/if}
