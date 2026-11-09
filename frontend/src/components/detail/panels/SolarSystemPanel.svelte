<script lang="ts">
	// The Planets page's Solar System tab: what is true of the eight planets
	// only. The sphere lineup above it is the tab's hero.
	import GroupStatCards from '../sections/GroupStatCards.svelte';
	import Section from '../sections/kit/Section.svelte';
	import CategoryCrossRefs from '../sections/crossref/CategoryCrossRefs.svelte';
	import SourcesFooter from '../sections/SourcesFooter.svelte';
	import MemberList from '../members/MemberList.svelte';
	import PlanetMassChart from '../charts/PlanetMassChart.svelte';
	import { categoryLabel } from '$lib/format/group';
	import { massCredits } from '$lib/credits/mass-sources';
	import type { GlobalGroupData, LocalizedGroupData } from '$lib/fetch/groups/details';
	import type { MembersState } from '../state/members-state.svelte';
	import type { LineupHero } from '../charts/lineup-hero.svelte';

	interface Props {
		global: GlobalGroupData;
		localized: LocalizedGroupData | null;
		members: MembersState;
		lineup: LineupHero;
	}

	let { global, localized, members, lineup }: Props = $props();

	let planets = $derived(global.solar_members ?? []);
</script>

<div class="flex flex-col gap-4">
	<GroupStatCards {global} {localized} tab="solar-system" />
	<CategoryCrossRefs slug={global.slug} />
	{#if planets.length > 0}
		<Section title={categoryLabel(global.slug)}>
			{#snippet header()}
				<MemberList members={planets} localizedNames={members.memberNames} />
			{/snippet}
		</Section>
		<PlanetMassChart members={planets} localizedNames={members.memberNames} />
	{/if}
	<!-- Credits for the lineup above and the masses of the chart, which this tab draws. -->
	<SourcesFooter
		global={null}
		pck={lineup.pck}
		works={lineup.shapeWorks}
		catalogues={massCredits(planets)}
		wikidata={lineup.wikidata}
		imagery={lineup.imagery}
	/>
</div>
