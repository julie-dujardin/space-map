<!--
  The map's credit bar, fed what the comparison row draws: the surface maps and
  relief on its spheres, and the meshes standing in for a shape or a craft.
  Follows the page, so a body two pages away is not credited until it is drawn.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { loadLayerCredits, type TextureSource } from '$lib/credits/texture-credits';
	import { layerLabel, type ImageryLayer } from '$lib/credits/imagery-layers';
	import {
		craftTier,
		fetchBundleMeta,
		modelTierCredit,
		shapeModelCredit,
		type ModelCredit
	} from '$lib/scene/objects/body/model';
	import { lineupDrawsShapeModel } from '$lib/scene/objects/body/shape-model-policy';
	import type { LineupBody } from '../detail/charts/BodyLineup.svelte';
	import AttributionBar, { type AttributionChip } from '../attribution/AttributionBar.svelte';
	import type { CreditRow, CreditSection } from '../attribution/AttributionPopover.svelte';

	interface Props {
		/** What the row is drawing right now, asides included. */
		bodies: LineupBody[];
	}

	let { bodies }: Props = $props();

	let textures = $state<Map<string, TextureSource> | null>(null);
	let relief = $state<Map<string, TextureSource> | null>(null);
	/** Mesh credits by bundle slug, kept across pages: a body that comes back
	 *  is credited again without another fetch. */
	let models = $state<Map<string, ModelCredit>>(new Map());
	const asked = new Set<string>();

	onMount(() => {
		loadLayerCredits('textures').then((c) => (textures = c));
		loadLayerCredits('displacement').then((c) => (relief = c));
	});

	// Same tier choice as the row, so the credit names the catalogue whose mesh
	// is on screen — a craft's two tiers can come from different ones.
	$effect(() => {
		for (const b of bodies) {
			const slug = b.model;
			if (!slug || asked.has(slug) || !(b.craft || lineupDrawsShapeModel(b))) continue;
			asked.add(slug);
			const craft = !!b.craft;
			fetchBundleMeta(slug)
				.then((meta) => {
					const credit =
						meta.kind === 'shape_model'
							? shapeModelCredit(meta)
							: craft
								? modelTierCredit(meta, craftTier(meta))
								: null;
					if (credit) models = new Map(models).set(slug, credit);
				})
				.catch(() => asked.delete(slug));
		}
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
				rows.push({
					href: credit.source,
					label: layers.length > 1 ? `${b.name} (${layerLabel(layer)})` : b.name,
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
			const credit = b.model ? models.get(b.model) : undefined;
			if (credit)
				rows.push({ href: credit.url, label: b.name, sub: credit.name, license: credit.license });
		}
		return rows;
	});

	const chips = $derived<AttributionChip[]>([
		{
			label: m.attribution_imagery(),
			names: [...new Set([...imageryRows, ...modelRows].map((r) => r.sub!))].sort()
		}
	]);

	const sections = $derived.by<CreditSection[]>(() => {
		const out: CreditSection[] = [];
		if (imageryRows.length)
			out.push({ title: m.attribution_section_imagery_all(), rows: imageryRows });
		if (modelRows.length) out.push({ title: m.attribution_section_models(), rows: modelRows });
		return out;
	});
</script>

<AttributionBar {chips} {sections} tone="surface" />
