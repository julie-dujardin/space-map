<!--
  The map's credit bar, fed what the comparison row draws: the surface maps and
  relief on its spheres, the meshes standing in for a shape or a craft, and the
  catalogues behind its stars.
  Follows the page, so a body two pages away is not credited until it is drawn.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { fetchStarCatalogueCredits } from '$lib/credits/star-sources';
	import { loadLayerCredits, type TextureSource } from '$lib/credits/texture-credits';
	import { rowQualifier, type ImageryLayer } from '$lib/credits/imagery-layers';
	import { lineupModelCredits } from '../detail/charts/lineup-model-credits.svelte';
	import { lineupDrawsShapeModel } from '$lib/scene/objects/body/shape-model-policy';
	import { isStarObjectId } from '$lib/fetch/extrasolar/ids';
	import { inSceneCredits, type ExtrasolarCredit } from '$lib/fetch/extrasolar/files';
	import type { LineupBody } from '../detail/charts/BodyLineup.svelte';
	import AttributionBar, { type AttributionChip } from '../attribution/AttributionBar.svelte';
	import type { CreditRow, CreditSection } from '../attribution/AttributionPopover.svelte';

	interface Props {
		/** What the row is drawing right now, asides included. */
		bodies: LineupBody[];
		/** Whether the stage is dark in either theme. */
		sky: boolean;
	}

	let { bodies, sky }: Props = $props();

	let textures = $state<Map<string, TextureSource> | null>(null);
	let relief = $state<Map<string, TextureSource> | null>(null);
	let catalogues = $state.raw<ExtrasolarCredit[]>([]);

	onMount(() => {
		loadLayerCredits('textures').then((c) => (textures = c));
		loadLayerCredits('displacement').then((c) => (relief = c));
		fetchStarCatalogueCredits().then((c) => (catalogues = c.filter(inSceneCredits)));
	});

	const imageryRows = $derived.by<CreditRow[]>(() => {
		const rows: CreditRow[] = [];
		for (const b of bodies) {
			if (b.craft) continue;
			const layers: Array<{ layer: ImageryLayer; credit: TextureSource }> = [];
			const surface = b.texture === false ? undefined : textures?.get(b.id);
			if (surface) layers.push({ layer: 'surface', credit: surface });
			const topography = b.displacement ? relief?.get(b.id) : undefined;
			if (topography) layers.push({ layer: 'topography', credit: topography });
			for (const { layer, credit } of layers) {
				const note = rowQualifier(layers.length > 1 ? layer : undefined, credit.artistImpression);
				rows.push({
					href: credit.source,
					label: note ? `${b.name} (${note})` : b.name,
					sub: credit.organisation,
					license: credit.license
				});
			}
		}
		return rows;
	});

	const modelRows = $derived.by<CreditRow[]>(() => {
		const rows: CreditRow[] = [];
		for (const b of bodies) {
			// The row records the credit of each mesh it drew, off the GLB itself.
			const drawsMesh = b.model && (b.craft || lineupDrawsShapeModel(b));
			const credit = drawsMesh ? lineupModelCredits.get(b.model!) : undefined;
			if (credit)
				rows.push({ href: credit.url, label: b.name, sub: credit.name, license: credit.license });
		}
		return rows;
	});

	const starRows = $derived<CreditRow[]>(
		bodies.some((b) => isStarObjectId(b.id))
			? catalogues.map((c) => ({
					href: c.source,
					label: c.name,
					sub: c.organisation,
					license: c.license
				}))
			: []
	);

	const chips = $derived<AttributionChip[]>([
		{
			label: m.attribution_imagery(),
			names: [...new Set([...imageryRows, ...modelRows].map((r) => r.sub!))].sort()
		},
		{
			label: m.attribution_stars(),
			names: [...new Set(starRows.filter((r) => r.license).map((r) => r.sub!))].sort()
		}
	]);

	const sections = $derived.by<CreditSection[]>(() => {
		const out: CreditSection[] = [];
		if (imageryRows.length)
			out.push({ title: m.attribution_section_imagery_all(), rows: imageryRows });
		if (modelRows.length) out.push({ title: m.attribution_section_models(), rows: modelRows });
		if (starRows.length) out.push({ title: m.attribution_section_stars(), rows: starRows });
		return out;
	});
</script>

<AttributionBar {chips} {sections} tone={sky ? 'sky' : 'surface'} />
