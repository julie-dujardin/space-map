<script lang="ts">
	// The Planets page's Exoplanets tab: the text of the item exoplanet, how
	// many there are, and the exoplanets the page lists.
	import GroupStatCards from '../sections/GroupStatCards.svelte';
	import ObjectDescription from '../sections/ObjectDescription.svelte';
	import Section from '../sections/kit/Section.svelte';
	import SourcesFooter from '../sections/SourcesFooter.svelte';
	import MemberList from '../members/MemberList.svelte';
	import { untrack } from 'svelte';
	import { isExtrasolarObjectId } from '$lib/fetch/extrasolar/ids';
	import { fetchExtrasolarMetadata, type ExtrasolarCredit } from '$lib/fetch/extrasolar/files';
	import { planetCatalogueCredits } from '$lib/credits/star-sources';
	import type { GroupDetailData } from '$lib/fetch/groups/details';
	import type { MembersState } from '../state/members-state.svelte';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		detail: GroupDetailData;
		members: MembersState;
	}

	let { detail, members }: Props = $props();

	let text = $derived(detail.localized?.exoplanets?.wikipedia);
	// The count and the names come from the planet catalogues.
	let credits = $state.raw<readonly ExtrasolarCredit[]>([]);
	$effect(() => {
		let live = true;
		untrack(fetchExtrasolarMetadata).then(
			(meta) => {
				if (live) credits = meta?.credits ?? [];
			},
			(e: unknown) => console.warn('[planets] no export credits:', e)
		);
		return () => {
			live = false;
		};
	});

	let exoplanets = $derived(
		(members.notableMembers ?? []).filter((mm) => mm.id && isExtrasolarObjectId(mm.id))
	);
</script>

<div class="flex flex-col gap-4">
	{#if detail.global}
		<GroupStatCards global={detail.global} localized={detail.localized} tab="exoplanets" />
	{/if}
	<ObjectDescription extract={text?.extract} wikipediaUrl={text?.url} />
	{#if exoplanets.length > 0}
		<Section title={m.planets_notable_exoplanets()}>
			{#snippet header()}
				<MemberList members={exoplanets} localizedNames={members.memberNames} />
			{/snippet}
		</Section>
	{/if}
	<SourcesFooter
		global={null}
		works={planetCatalogueCredits(credits)}
		wikipediaLicensed={!!text?.extract}
	/>
</div>
