<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalGroupData, LocalizedGroupData } from '$lib/fetch/groups/details';
	import { formatIsoDate } from '$lib/format/date';
	import Section from './Section.svelte';
	import Row from './Row.svelte';
	import EntityLinks from './EntityLinks.svelte';

	interface Props {
		global: GlobalGroupData | null;
		localized: LocalizedGroupData | null;
	}

	let { global, localized }: Props = $props();

	let earliestLaunch = $derived(global?.earliest_launch);
	let operators = $derived(localized?.operators ?? []);
	let countries = $derived(localized?.country_of_origin ?? []);
	let hasContent = $derived(!!earliestLaunch || operators.length > 0 || countries.length > 0);
</script>

{#if hasContent}
	<Section title={m.mission()}>
		{#if earliestLaunch}
			<Row label={m.group_earliest_launch()} value={formatIsoDate(earliestLaunch)} />
		{/if}
		{#if operators.length > 0}
			<Row label={m.property_name_operators()}>
				<EntityLinks entities={operators} />
			</Row>
		{/if}
		{#if countries.length > 0}
			<Row label={m.property_name_country_of_origin()}>
				<EntityLinks entities={countries} />
			</Row>
		{/if}
	</Section>
{/if}
