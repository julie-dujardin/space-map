<script lang="ts">
	import ZoneCategoryLinks from '../../sections/crossref/ZoneCategoryLinks.svelte';
	import CategoryCrossRefs from '../../sections/crossref/CategoryCrossRefs.svelte';
	import CategoryChildTiles from '../../sections/crossref/CategoryChildTiles.svelte';
	import BodyCategoryTile from '../../sections/crossref/BodyCategoryTile.svelte';
	import BodyTile from '../../sections/crossref/BodyTile.svelte';
	import RingSystemTiles from '../../sections/crossref/RingSystemTiles.svelte';
	import PlanetarySystemTiles from '../../sections/crossref/PlanetarySystemTiles.svelte';
	import PropertyMemberList from '../../sections/PropertyMemberList.svelte';
	import ChildGroups from '../../sections/ChildGroups.svelte';
	import CultureFigures from '../../sections/CultureFigures.svelte';
	import FeatureTypeFamilies from '../../sections/FeatureTypeFamilies.svelte';
	import GroupProperties from '../../sections/GroupProperties.svelte';
	import GroupOrbitMap from '../../charts/GroupOrbitMap.svelte';
	import CountPerBodyChart from '../../charts/CountPerBodyChart.svelte';
	import PlanetPlots from '../../charts/PlanetPlots.svelte';
	import RingMassChart from '../../charts/RingMassChart.svelte';
	import StarDiagram from '../../charts/StarDiagram.svelte';
	import SolarSystemMassChart from '../../charts/SolarSystemMassChart.svelte';
	import { propertyFigure } from './group-figures';
	import { PROPERTY_CHART } from './property-charts';
	import {
		categoryPlotType,
		classNameFromSlug,
		orbitClassLabel,
		scatterZoneSlugs
	} from '$lib/charts/orbit-zones';
	import { byRegion } from '../../../layers/sky-culture-list';
	import type { Source } from '../../sections/SourcesFooter.svelte';
	import { fetchPickableCultures } from '$lib/fetch/extrasolar/skycultures';
	import {
		CAT_CONSTELLATIONS,
		CAT_SATELLITES,
		CAT_SOLAR_SYSTEM,
		CAT_STARS,
		CAT_STRUCTURE_ACTIVITY,
		SKY_CULTURE_SLUG_PREFIX
	} from '$lib/fetch/groups/registry';
	import { EARTH_ID } from '$lib/constants';
	import { PROPERTY_ACCENT, type CategoryConfig } from '$lib/state/category-config';
	import type { FeatureFamily, GroupDetailData } from '$lib/fetch/groups/details';
	import type { MembersState } from '../../state/members-state.svelte';
	import { groupTypeLabelPlural } from '$lib/format/group';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';

	interface Props {
		slug: string;
		cat: CategoryConfig;
		groupDetail: GroupDetailData | null;
		members: MembersState;
		/** The overview is the tab in view. */
		active: boolean;
		/** The sources of the figures of a culture page, for the footer. */
		onFigureCredits?: (credits: Source[]) => void;
	}

	let { slug, cat, groupDetail, members, active, onFigureCredits }: Props = $props();

	let notableMembers = $derived(members.notableMembers);
	let memberNames = $derived(members.memberNames);
	// A small-body zone's orbit-class name (e.g. "MBA") drives its tiles.
	let smallBodyZoneClass = $derived(members.isSmallBodyZone ? classNameFromSlug(slug) : null);
	// Categories render the orbit map here; class/NEO/PHA pages get it from
	// GroupProperties (slug-derived). Chips fold into GroupOrbitMap, so both show them.
	let categoryPlot = $derived(categoryPlotType(slug));
	// Moons category: the per-planet/dwarf bar chart replaces the notable-members
	// strip and members list this page deliberately omits.
	let moonCounts = $derived(cat.moons ? groupDetail?.global?.moon_counts : undefined);
	// Probes category: where the fleet was sent. Rows open the target's
	// overview, whose probes strip is the list behind the bar.
	let probeTargets = $derived(groupDetail?.global?.probe_targets);
	// The libration points are rows on a collection, not a body, so their label
	// comes from the zone names rather than the bundle's body_names.
	let targetNames = $derived.by(() => {
		const names = { ...(groupDetail?.localized?.body_names ?? {}) };
		for (const row of probeTargets ?? []) {
			const cls = row.primary_id ? classNameFromSlug(row.primary_id) : null;
			if (cls) names[row.primary_id!] = orbitClassLabel(cls);
		}
		return names;
	});
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
	// A culture page lists all its figures. Its chips are the ones with a page.
	let cultureKey = $derived(
		slug.startsWith(SKY_CULTURE_SLUG_PREFIX) ? slug.slice(SKY_CULTURE_SLUG_PREFIX.length) : null
	);
	// The Constellations page, by the regions of the layer's picker.
	let isConstellations = $derived(slug === CAT_CONSTELLATIONS);
	let cultureRegions = $state.raw<FeatureFamily[] | null>(null);
	$effect(() => {
		const wanted = isConstellations;
		const locale = getLocale();
		cultureRegions = null;
		if (!wanted) return;
		let current = true;
		fetchPickableCultures().then(
			(cultures) => {
				if (!current || !cultures) return;
				cultureRegions = byRegion(cultures, locale).map((region) => ({
					key: region.group,
					name: region.label,
					n: region.cultures.length,
					types: region.cultures.map((c) => `${SKY_CULTURE_SLUG_PREFIX}${c.key}`)
				}));
			},
			(e: unknown) => console.warn('[constellations] no sky cultures:', e)
		);
		return () => {
			current = false;
		};
	});
	/** The meta node, whose children are the property collections themselves. */
	let isStructureActivity = $derived(slug === CAT_STRUCTURE_ACTIVITY);
</script>

{#if cat.crossRefs}
	<CategoryCrossRefs {slug} />
{/if}
{#if cat.spacecraft}
	<div class="grid grid-cols-2 gap-2">
		<BodyTile id={EARTH_ID} name={m.earth()} />
		<BodyCategoryTile slug={CAT_SOLAR_SYSTEM} />
	</div>
{/if}
{#if smallBodyZoneClass}
	<ZoneCategoryLinks className={smallBodyZoneClass} />
{/if}
{#if cat.solarSystem && visibleChildGroups.length}
	<CategoryChildTiles childGroups={visibleChildGroups} />
{/if}
{#if cat.satelliteSystems && notableMembers && notableMembers.length > 0}
	<PlanetarySystemTiles members={notableMembers} localizedNames={memberNames} />
{/if}
{#if cat.ringSystems && notableMembers && notableMembers.length > 0}
	<RingSystemTiles members={notableMembers} localizedNames={memberNames} />
	<RingMassChart members={notableMembers} localizedNames={memberNames} />
{/if}
{#if cat.property && notableMembers && notableMembers.length > 0}
	{@const chart = PROPERTY_CHART[cat.property]}
	<PropertyMemberList
		members={notableMembers}
		names={memberNames}
		accent={PROPERTY_ACCENT[cat.property]}
		figure={(mm) => propertyFigure(mm, cat.property)}
	/>
	<chart.component members={notableMembers} localizedNames={memberNames} {...chart.extra?.()} />
{/if}
{#if cat.planets}
	<!-- Where the exoplanets are; the planet families, then where every planet
	     lies by mass. -->
	<div class="grid grid-cols-2 gap-2">
		<BodyCategoryTile slug={CAT_STARS} />
		<BodyCategoryTile slug={CAT_SOLAR_SYSTEM} />
	</div>
	{#if visibleChildGroups.length}
		<ChildGroups childGroups={visibleChildGroups} />
	{/if}
	<PlanetPlots
		solarMembers={groupDetail?.global?.solar_members ?? []}
		localizedNames={memberNames}
		{active}
	/>
{/if}
{#if cat.stars}
	<StarDiagram members={notableMembers ?? []} localizedNames={memberNames} {active} />
{/if}
{#if cat.solarSystem}
	<SolarSystemMassChart />
{/if}
{#if moonCounts && moonCounts.length > 0}
	<CountPerBodyChart
		entries={moonCounts}
		title={m.group_moons_per_planet()}
		tab="members"
		names={groupDetail?.localized?.body_names}
	/>
{/if}
{#if probeTargets && probeTargets.length > 0}
	<CountPerBodyChart entries={probeTargets} title={m.group_targets_title()} names={targetNames} />
{/if}
{#if categoryPlot && groupDetail?.global}
	<GroupOrbitMap
		global={groupDetail.global}
		plotOverride={categoryPlot}
		seeAll={cat.spacecraft ? CAT_SATELLITES : undefined}
		title={cat.spacecraft ? m.group_earth_orbit_map() : undefined}
	/>
{/if}
{#if cultureKey}
	<CultureFigures culture={cultureKey} onCredits={onFigureCredits} />
{:else if visibleChildGroups.length && !cat.solarSystem && !cat.planets && !cat.spacecraft}
	<!-- Surface Features groups its 57 type chips by landform family. -->
	{#if featureFamilies}
		<FeatureTypeFamilies families={featureFamilies} childGroups={visibleChildGroups} />
	{:else if cultureRegions}
		<FeatureTypeFamilies
			families={cultureRegions}
			childGroups={visibleChildGroups}
			heading={groupTypeLabelPlural('sky_culture')}
			collapsedTo={Infinity}
		/>
	{:else if isConstellations}
		<!-- The regions are on their way. -->
	{:else if isStructureActivity}
		<!-- Chips would name the collections; tiles draw what each holds.
		     Full width here: every child is a drawn collection, so the
		     tiles are the page rather than a footer to it. -->
		<CategoryChildTiles childGroups={visibleChildGroups} wide />
	{:else}
		<ChildGroups childGroups={visibleChildGroups} />
	{/if}
{/if}
<GroupProperties global={groupDetail?.global ?? null} localized={groupDetail?.localized ?? null} />
