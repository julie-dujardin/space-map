<script lang="ts">
	/** The vehicle itself — what it weighs and how big it is. Kept apart from
	 *  Mission, which is who flew it and why. */
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatQuantity } from '$lib/format/quantities';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	let isSpacecraft = $derived(global?.type === 'spacecraft' || global?.type === 'debris');
	let wd = $derived(global?.wikidata);
	let hasFields = $derived(!!(wd?.mass || wd?.length || wd?.width));
	let hasContent = $derived(isSpacecraft && hasFields);
</script>

{#if hasContent}
	<Section title={m.spacecraft_properties()}>
		{#if wd?.mass}
			<Row label={m.property_name_mass()} value={formatQuantity(wd.mass)} />
		{/if}
		{#if wd?.length}
			<Row label={m.property_name_length()} value={formatQuantity(wd.length)} />
		{/if}
		{#if wd?.width}
			<Row label={m.property_name_width()} value={formatQuantity(wd.width)} />
		{/if}
	</Section>
{/if}
