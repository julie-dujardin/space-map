<script lang="ts">
	import ZoneCategoryLinks from '../../sections/crossref/ZoneCategoryLinks.svelte';
	import CategoryCrossRefs from '../../sections/crossref/CategoryCrossRefs.svelte';
	import CategoryChildTiles from '../../sections/crossref/CategoryChildTiles.svelte';
	import RingSystemTiles from '../../sections/crossref/RingSystemTiles.svelte';
	import PlanetarySystemTiles from '../../sections/crossref/PlanetarySystemTiles.svelte';
	import PropertyMemberList from '../../sections/PropertyMemberList.svelte';
	import ChildGroups from '../../sections/ChildGroups.svelte';
	import FeatureTypeFamilies from '../../sections/FeatureTypeFamilies.svelte';
	import GroupProperties from '../../sections/GroupProperties.svelte';
	import GroupOrbitMap from '../../charts/GroupOrbitMap.svelte';
	import CountPerBodyChart from '../../charts/CountPerBodyChart.svelte';
	import PlanetMassChart from '../../charts/PlanetMassChart.svelte';
	import RingMassChart from '../../charts/RingMassChart.svelte';
	import OceanVolumeChart from '../../charts/OceanVolumeChart.svelte';
	import AtmospherePressureChart from '../../charts/AtmospherePressureChart.svelte';
	import ValuePerBodyChart from '../../charts/ValuePerBodyChart.svelte';
	import RadiationDoseChart from '../../charts/RadiationDoseChart.svelte';
	import TectonicStyleChart from '../../charts/TectonicStyleChart.svelte';
	import VolcanismStatusChart from '../../charts/VolcanismStatusChart.svelte';
	import SolarSystemMassChart from '../../charts/SolarSystemMassChart.svelte';
	import { propertyFigure } from './group-figures';
	import {
		categoryPlotType,
		classNameFromSlug,
		orbitClassLabel,
		scatterZoneSlugs
	} from '$lib/charts/orbit-zones';
	import { CAT_STRUCTURE_ACTIVITY } from '$lib/fetch/groups/registry';
	import { PROPERTY_ACCENT, type CategoryConfig } from '$lib/state/category-config';
	import { fieldParts, powerParts } from '$lib/format/activity';
	import type { GroupDetailData } from '$lib/fetch/groups/details';
	import type { MembersState } from '../../state/members-state.svelte';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		slug: string;
		cat: CategoryConfig;
		groupDetail: GroupDetailData | null;
		members: MembersState;
	}

	let { slug, cat, groupDetail, members }: Props = $props();

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
	/** The meta node, whose children are the property collections themselves. */
	let isStructureActivity = $derived(slug === CAT_STRUCTURE_ACTIVITY);
</script>

{#if cat.crossRefs}
	<CategoryCrossRefs {slug} />
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
	<PropertyMemberList
		members={notableMembers}
		names={memberNames}
		accent={PROPERTY_ACCENT[cat.property]}
		figure={(mm) => propertyFigure(mm, cat.property)}
	/>
	{#if cat.property === 'oceans'}
		<OceanVolumeChart members={notableMembers} localizedNames={memberNames} />
	{:else if cat.property === 'atmospheres'}
		<AtmospherePressureChart members={notableMembers} localizedNames={memberNames} />
	{:else if cat.property === 'volcanism'}
		<VolcanismStatusChart members={notableMembers} />
	{:else if cat.property === 'tectonics'}
		<TectonicStyleChart members={notableMembers} />
	{:else if cat.property === 'magnetic-fields'}
		<ValuePerBodyChart
			members={notableMembers}
			localizedNames={memberNames}
			title={m.group_magnetic_field_title()}
			value={(e) =>
				e.activity?.magnetism?.surface_field_t_upper_limit
					? undefined
					: e.activity?.magnetism?.surface_field_t}
			text={(v) => `${fieldParts(v).value} ${fieldParts(v).unit}`}
		/>
	{:else if cat.property === 'tidal-heating'}
		<ValuePerBodyChart
			members={notableMembers}
			localizedNames={memberNames}
			title={m.group_tidal_power_title()}
			value={(e) => e.activity?.tidal?.power_w}
			text={(v) => `${powerParts(v).value} ${powerParts(v).unit}`}
		/>
	{:else if cat.property === 'radiation'}
		<RadiationDoseChart members={notableMembers} localizedNames={memberNames} />
	{/if}
{/if}
{#if cat.planets && notableMembers && notableMembers.length > 0}
	<PlanetMassChart members={notableMembers} localizedNames={memberNames} />
{/if}
{#if cat.solarSystem}
	<SolarSystemMassChart />
{/if}
{#if moonCounts && moonCounts.length > 0}
	<CountPerBodyChart entries={moonCounts} title={m.group_moons_per_planet()} tab="members" />
{/if}
{#if probeTargets && probeTargets.length > 0}
	<CountPerBodyChart entries={probeTargets} title={m.group_targets_title()} names={targetNames} />
{/if}
{#if categoryPlot && groupDetail?.global}
	<GroupOrbitMap global={groupDetail.global} plotOverride={categoryPlot} />
{/if}
{#if visibleChildGroups.length && !cat.solarSystem}
	<!-- Surface Features groups its 57 type chips by landform family. -->
	{#if featureFamilies}
		<FeatureTypeFamilies families={featureFamilies} childGroups={visibleChildGroups} />
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
