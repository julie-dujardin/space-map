<script lang="ts">
	import PaginatedMemberList from '../members/PaginatedMemberList.svelte';
	import SourcesFooter from '../sections/SourcesFooter.svelte';
	import type { MembersState } from '../state/members-state.svelte';
	import type { LineupHero } from '../charts/lineup-hero.svelte';
	import type { GroupDetailData } from '$lib/fetch/groups/details';
	import type { PositionedBody } from '$lib/types/objects';

	interface Props {
		isGroupMode: boolean;
		groupDetail: GroupDetailData | null;
		body: PositionedBody | null;
		members: MembersState;
		lineup: LineupHero;
	}

	let { isGroupMode, groupDetail, body, members, lineup }: Props = $props();
</script>

<div class="flex flex-col gap-3 p-1">
	{#if isGroupMode && groupDetail?.global}
		<PaginatedMemberList
			source={{ kind: 'group', slug: groupDetail.global.slug }}
			totalCount={members.memberTotal}
			localizedNames={members.memberNames}
			fallback={members.notableMembers ?? []}
		/>
	{:else if body && members.notableMembers && members.notableMembers.length > 0}
		<PaginatedMemberList
			source={{ kind: 'parent', parentId: body.data.id }}
			totalCount={members.memberTotal}
			localizedNames={members.memberNames}
			fallback={members.notableMembers}
		/>
	{/if}
	<!-- Credits for the spheres this tab draws — a planet's moons, or the
	     Solar System's own row. -->
	{#if lineup.isMoonLineup || lineup.solarSystemLineup}
		<SourcesFooter
			global={null}
			pck={lineup.pck}
			lightcurvePole={lineup.lightcurvePole}
			wikidata={lineup.wikidata}
			imagery={lineup.imagery}
		/>
	{/if}
</div>
