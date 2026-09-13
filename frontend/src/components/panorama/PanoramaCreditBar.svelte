<!--
  The map's credit bar, fed the panorama's sources: whose picture it is, the
  archive record it came from, and what the traverse minimap is drawn from.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { PanoramaEntry } from '$lib/fetch/objects/object-data';
	import type { LayerCredit } from '$lib/flatmap/layers';
	import { safeHttpUrl } from '$lib/utils';
	import AttributionBar, { type AttributionChip } from '../attribution/AttributionBar.svelte';
	import type { CreditSection } from '../attribution/AttributionPopover.svelte';

	interface Props {
		entry: PanoramaEntry;
		/** What the traverse minimap is drawn from. */
		mapCredits: readonly LayerCredit[];
	}

	let { entry, mapCredits }: Props = $props();

	const chips = $derived<AttributionChip[]>([
		{ label: m.attribution_imagery(), names: entry.credit ? [entry.credit] : [] },
		{
			label: m.attribution_map(),
			names: [...new Set(mapCredits.map((c) => c.organisation))].filter(Boolean)
		}
	]);

	const sections = $derived.by<CreditSection[]>(() => {
		const creditUrl = safeHttpUrl(entry.credit_url);
		const sourceUrl = safeHttpUrl(entry.source_url);
		const panorama: CreditSection = { title: m.attribution_section_panorama(), rows: [] };
		if (entry.credit && creditUrl) panorama.rows.push({ href: creditUrl, label: entry.credit });
		if (sourceUrl)
			panorama.rows.push({ href: sourceUrl, label: m.panorama_source(), sub: entry.id });
		const out = [panorama];
		if (mapCredits.length) {
			out.push({
				title: m.attribution_section_imagery(),
				rows: mapCredits.map((c) => ({ href: c.source, label: c.organisation, sub: c.attribution }))
			});
		}
		return out;
	});
</script>

<AttributionBar {chips} {sections} />
