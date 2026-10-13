<!--
  The data tables: one row for each map, each ring bundle and each 3D model.
  The page around them draws before they do, so the component takes the
  payload already resolved.
-->
<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { formatIsoDate } from '$lib/format/date';
	import { formatBytes } from '$lib/format/bytes';
	import { ltrIsolate } from '$lib/format/bidi';
	import { formatNumber, formatQuantity, formatUnit, ucfirst } from '$lib/format/quantities';
	import { getLocale } from '$lib/host';
	import { layerLabel } from '$lib/credits/imagery-layers';
	import { COMPARABLES } from '$lib/compare/comparables';
	import { rocketBySlug, rocketsCompareHref } from '$lib/compare/rockets';
	import { bodyHref } from '$lib/state/page-href';
	import type { LabelMap } from '$lib/fetch/position/labels';
	import PageContents, { type ContentsEntry } from '../nav/PageContents.svelte';
	import {
		listedSources,
		mapFigures,
		modelFigures,
		totals,
		type AboutData,
		type CraftGroup,
		type CraftModel,
		type Credit,
		type DataSystem,
		type LightcurveModels,
		type MapPatch,
		type MapSource,
		type Model,
		type Ring,
		type RingWorld,
		type ShapeModel,
		type World,
		type WorldMap
	} from '$lib/about/data-payload';

	interface Props {
		data: AboutData;
		/** Names in the language of the reader, by object id. */
		labels: LabelMap;
	}

	let { data, labels }: Props = $props();

	/** One row of a table. The meaning of its figures is that of the header
	 *  above it. */
	interface Line {
		key: string;
		name: string;
		href?: string;
		/** A remark beside the name. */
		tag?: string;
		/** Lines under the name. */
		notes?: string[];
		resolution: string;
		/** Absent for a row that states none. */
		extent?: string;
		/** Empty for a table with no such column. */
		count: string;
		/** The count, as a narrow screen states it under the name. */
		countStated?: string;
		size: string;
		sources: Credit[];
		/** The name takes the column of the world too. */
		wide?: boolean;
		/** Rows of the areas inside this one. */
		children?: Line[];
	}

	/** The name of a body in the language of the reader, else its English one. */
	function named(id: string | undefined, fallback: string): string {
		return (id && labels.get(id)?.name) || fallback;
	}

	const sum = $derived(totals(data));

	const EM_DASH = '—';

	// On a very wide screen the table goes past the column of the page to the
	// gutter of the end side, and the source has a column. Below that, the
	// source goes under its row. The start side stays clear for the contents.
	const TABLE = '2xl:w-[min(93rem,50vw_+_25rem)]';
	// Column widths, shared by the headers and every row.
	const WORLD = 'sm:w-28 sm:shrink-0';
	const NAME = 'min-w-0 flex-1 2xl:w-60 2xl:flex-none';
	// The columns of the world and of the name, with the gap between them.
	const WIDE_NAME = 'min-w-0 flex-1 2xl:w-92 2xl:flex-none';
	const RESOLUTION = 'w-20 shrink-0 text-end sm:w-24';
	const EXTENT = 'hidden w-48 shrink-0 text-end lg:block';
	const COUNT = 'hidden w-20 shrink-0 text-end sm:block';
	const SIZE = 'w-20 shrink-0 text-end';
	const SOURCE = 'mt-1 w-full min-w-0 2xl:mt-0 2xl:w-auto 2xl:flex-1';

	const RING_LABELS: Record<string, () => string> = {
		inner: m.about_data_ring_inner,
		primary: m.about_data_ring_main,
		outer: m.about_data_ring_outer
	};

	const PROVENANCE_LABELS: Record<string, () => string> = {
		missions: m.about_data_shape_missions,
		radar: m.about_data_shape_radar
	};

	const KIND_LABELS: Record<string, () => string> = {
		probe: m.category_name_probes,
		earth_sat: m.category_name_satellites,
		station: m.compare_preset_stations,
		lander: m.about_data_kind_landers,
		robot: m.about_data_kind_rovers,
		rocket: m.compare_preset_rockets,
		generic_sat: m.group_type_plural_bus,
		comparable: m.compare_comparables
	};

	function systemName(system: DataSystem): string {
		return system.name === null ? m.credits_other_bodies() : named(system.primary_id, system.name);
	}

	function kindName(kind: string): string {
		return KIND_LABELS[kind]?.() ?? ucfirst(kind.replaceAll('_', ' '));
	}

	function count(n: number): string {
		return n.toLocaleString(getLocale());
	}

	/** "10.2 m", "1.3 km". The rounded figure decides the unit, so 999.6 m
	 *  reads "1 km". */
	function distance(metres: number): string {
		const rounded = Number(metres.toPrecision(3));
		return rounded >= 1000
			? formatQuantity({ value: rounded / 1000, unit: 'kilometre' }, true)
			: formatQuantity({ value: rounded, unit: 'metre' }, true);
	}

	function resolution(metres: number | undefined): string {
		return metres === undefined ? EM_DASH : distance(metres);
	}

	function pixels(width: number | undefined, height: number | undefined): string {
		if (width === undefined || height === undefined) return EM_DASH;
		return ltrIsolate(m.about_data_pixels({ width: count(width), height: count(height) }));
	}

	function ground(patch: MapPatch): string {
		if (patch.width_km === undefined || patch.height_km === undefined) return EM_DASH;
		const unit = formatUnit('kilometre', true);
		return ltrIsolate(`${formatNumber(patch.width_km)} × ${formatNumber(patch.height_km)} ${unit}`);
	}

	/** "74,510 – 140,390 km", from the centre of the body. */
	function radii(ring: Ring): string {
		const unit = formatUnit('kilometre', true);
		return ltrIsolate(
			`${formatNumber(ring.inner_radius_km)} – ${formatNumber(ring.outer_radius_km)} ${unit}`
		);
	}

	/** "-60°", "+84°". */
	function latitude(degrees: number): string {
		const figure = new Intl.NumberFormat(getLocale(), {
			signDisplay: 'exceptZero',
			maximumFractionDigits: 0
		}).format(degrees);
		return ltrIsolate(`${figure}°`);
	}

	function sourceNote(source: MapSource, sharpened: boolean): string {
		const figure = resolution(source.m_per_px);
		let note = figure;
		if (source.role === 'detail') note = m.about_data_source_detail({ resolution: figure });
		else if (sharpened) note = m.about_data_source_colour({ resolution: figure });
		if (!source.lat_range) return note;
		const [south, north] = source.lat_range;
		return m.about_data_latitudes({
			source: note,
			south: latitude(south),
			north: latitude(north)
		});
	}

	/** What the row of a map does not say, one line each: the sources of its
	 *  pyramid, then the facts of the map itself. */
	function mapNotes(map: WorldMap): string[] {
		const sources = map.tiles ? listedSources(map.tiles) : [];
		const sharpened = sources.some((source) => source.role === 'detail');
		const made = sources
			.filter((source) => source.m_per_px !== undefined)
			.map((source) => sourceNote(source, sharpened));
		const facts: string[] = [];
		if (map.frames) facts.push(m.about_data_frames({ count: count(map.frames) }));
		const step = mapFigures(map).height_step_m;
		if (step !== undefined) facts.push(m.about_data_height_step({ step: distance(step) }));
		return [made, facts].filter((line) => line.length > 0).map((line) => line.join(' · '));
	}

	function patchLine(patch: MapPatch): Line {
		return {
			key: patch.id,
			name: patch.name,
			resolution: resolution(patch.m_per_px),
			extent: ground(patch),
			count: count(patch.tiles),
			countStated: m.about_data_tiles_count({ count: count(patch.tiles) }),
			size: formatBytes(patch.size_bytes),
			sources: [patch]
		};
	}

	function mapLine(body: World, map: WorldMap): Line {
		const figures = mapFigures(map);
		const tiles = figures.tiles;
		return {
			key: map.id,
			name: ucfirst(
				body.no_surface && map.layer === 'surface'
					? m.temperature_part_cloud_top()
					: layerLabel(map.layer)
			),
			tag: map.alternate ? m.about_data_alternate() : undefined,
			notes: mapNotes(map),
			resolution: resolution(figures.m_per_px),
			extent: pixels(figures.width, figures.height),
			count: tiles === undefined ? EM_DASH : count(tiles),
			countStated:
				tiles === undefined ? undefined : m.about_data_tiles_count({ count: count(tiles) }),
			size: formatBytes(figures.size_bytes),
			sources: [map],
			children: map.tiles?.patches?.map(patchLine)
		};
	}

	/** A world with one bundle needs no name for it. */
	function ringLine(world: RingWorld, ring: Ring): Line {
		return {
			key: ring.id,
			name: world.rings.length === 1 ? m.tab_rings() : (RING_LABELS[ring.id]?.() ?? ring.id),
			resolution: distance(ring.km_per_sample * 1000),
			extent: radii(ring),
			count: count(ring.samples),
			countStated: m.about_data_samples_count({ count: count(ring.samples) }),
			size: formatBytes(ring.size_bytes),
			sources: ring.sources
		};
	}

	/** The figures of a model. The caller gives the row its name. */
	function modelLine(model: Model, name: string, notes: string[] = []): Line {
		const figures = modelFigures(model);
		const low =
			figures.low_triangles === undefined
				? []
				: [m.about_data_low_detail({ count: count(figures.low_triangles) })];
		return {
			key: model.slug,
			name,
			notes: [...notes, ...low],
			resolution: count(figures.triangles),
			extent: model.extent_m === undefined ? undefined : distance(model.extent_m),
			count: '',
			size: formatBytes(figures.size_bytes),
			sources: model.sources
		};
	}

	function shapeLine(model: ShapeModel): Line {
		return modelLine(model, PROVENANCE_LABELS[model.provenance]?.() ?? model.provenance);
	}

	/** A model takes the name of the one object that it draws, else that of
	 *  its rocket or of its scale reference, else its slug. */
	function craftLine(model: CraftModel): Line {
		const shared =
			model.objects > 1 ? [m.about_data_craft_count({ count: count(model.objects) })] : [];
		const line = { ...modelLine(model, model.slug, shared), wide: true };
		if (model.object) {
			const name = named(model.object.id, model.object.name);
			return { ...line, name, href: bodyHref(model.object.id, name) };
		}
		const rocket = rocketBySlug(model.slug);
		if (rocket) return { ...line, name: rocket.label(), href: rocketsCompareHref(rocket.slug) };
		const comparable = COMPARABLES.find((entry) => entry.slug === model.slug);
		return comparable ? { ...line, name: comparable.label() } : line;
	}

	function craftLines(group: CraftGroup): Line[] {
		const collator = new Intl.Collator(getLocale(), { sensitivity: 'base', numeric: true });
		return group.models.map(craftLine).sort((a, b) => collator.compare(a.name, b.name));
	}

	function lightcurveLine(shapes: LightcurveModels): Line {
		return {
			key: 'lightcurve',
			name: m.about_data_shape_lightcurve(),
			notes: [
				[
					m.about_data_asteroids_count({ count: count(shapes.worlds) }),
					m.about_data_models_count({ count: count(shapes.models) })
				].join(' · ')
			],
			resolution: count(shapes.triangles),
			count: '',
			size: formatBytes(shapes.size_bytes),
			sources: shapes.sources
		};
	}

	const contents = $derived<ContentsEntry[]>([
		{
			id: 'maps',
			label: m.about_data_maps(),
			children: data.systems.map((system) => ({
				id: `maps-${system.id ?? 'other'}`,
				label: systemName(system)
			}))
		},
		{ id: 'rings', label: m.tab_rings() },
		{
			id: 'models',
			label: m.status_section_models(),
			children: [
				{ id: 'models-worlds', label: m.about_data_worlds() },
				...data.models.craft.map((craft) => ({
					id: `models-${craft.kind}`,
					label: kindName(craft.kind)
				}))
			]
		}
	]);

	const stats = $derived([
		{ label: m.about_data_worlds(), value: count(sum.worlds) },
		{ label: m.about_data_maps(), value: count(sum.maps) },
		{ label: m.about_data_column_tiles(), value: count(sum.tiles) },
		{ label: m.tab_rings(), value: count(sum.rings) },
		{ label: m.status_section_models(), value: count(sum.models) },
		{ label: m.about_data_column_size(), value: formatBytes(sum.size_bytes) }
	]);
</script>

<!-- Under a row the name of the source is as small as the notes there. -->
{#snippet source(credit: Credit)}
	{@const style = 'text-xs text-muted-foreground 2xl:text-sm 2xl:text-foreground'}
	<div>
		{#if credit.source}
			<a
				href={credit.source}
				target="_blank"
				rel="noopener noreferrer"
				class="{style} hover:underline underline-offset-2">{credit.organisation}</a
			>
		{:else}
			<span class={style}>{credit.organisation}</span>
		{/if}
		{#if credit.attribution}
			<!-- A credit line is in its own language, whatever that of the page. -->
			<div dir="auto" class="text-xs wrap-anywhere text-muted-subtle rtl:text-right">
				{credit.attribution}
			</div>
		{/if}
	</div>
{/snippet}

{#snippet section(id: string, title: string, intro: string)}
	<h2 {id} class="mt-12 mb-1 scroll-mt-10 text-base font-semibold text-foreground">{title}</h2>
	<p class="max-w-prose text-muted-foreground">{intro}</p>
{/snippet}

<!-- `world` is false for a table whose names take the column of the world.
     The header stays in view down the length of its table. -->
{#snippet header(world: boolean, name: string, resolution: string, counted: string)}
	<div
		class="sticky top-0 z-10 mt-4 flex items-baseline gap-4 border-b border-border bg-bg pt-2 pb-1.5 text-xs font-semibold uppercase tracking-wider text-muted-subtle"
	>
		{#if world}
			<div class="hidden {WORLD} sm:block">{m.about_data_column_world()}</div>
		{/if}
		<div class={world ? NAME : WIDE_NAME}>{name}</div>
		<div class={RESOLUTION}>{resolution}</div>
		<div class={EXTENT}>{m.about_data_column_extent()}</div>
		<div class={COUNT}>{counted}</div>
		<div class={SIZE}>{m.about_data_column_size()}</div>
		<div class="hidden min-w-0 flex-1 2xl:block">{m.status_column_source()}</div>
	</div>
{/snippet}

<!-- The figures a narrow screen has no column for go under the name. `bdi`
     keeps the order of a Latin designation in an RTL page. -->
{#snippet line(row: Line, indent = false)}
	<div class="flex flex-wrap items-baseline gap-x-4">
		<div class="{row.wide ? WIDE_NAME : NAME} wrap-anywhere {indent ? 'ps-4' : ''}">
			{#if row.href}
				<a href={row.href} class="hover:underline underline-offset-2"><bdi>{row.name}</bdi></a>
			{:else}
				<bdi>{row.name}</bdi>
			{/if}
			{#if row.tag}
				<span class="text-muted-subtle">· {row.tag}</span>
			{/if}
			{#if row.extent}
				<div class="text-xs text-muted-subtle tabular-nums lg:hidden">{row.extent}</div>
			{/if}
			{#if row.countStated}
				<div class="text-xs text-muted-subtle tabular-nums sm:hidden">{row.countStated}</div>
			{/if}
			{#each row.notes ?? [] as note (note)}
				<div class="text-xs text-muted-subtle">{note}</div>
			{/each}
		</div>
		<div class="{RESOLUTION} tabular-nums">{row.resolution}</div>
		<div class="{EXTENT} text-muted-foreground tabular-nums">{row.extent ?? EM_DASH}</div>
		<div class="{COUNT} text-muted-foreground tabular-nums">{row.count}</div>
		<div class="{SIZE} text-muted-foreground tabular-nums">{row.size}</div>
		<div class="{SOURCE} flex flex-col gap-1 {indent ? 'ps-4 2xl:ps-0' : ''}">
			{#each row.sources as credit (credit)}
				{@render source(credit)}
			{/each}
		</div>
	</div>
{/snippet}

<!-- The rows of one world. `id` is absent for a row that stands for many.
     `grouped` is true under a group heading, which takes the level above. -->
{#snippet world(id: string | undefined, fallback: string, lines: Line[], grouped = false)}
	{@const name = named(id, fallback)}
	<div class="border-b border-border py-2.5 sm:flex sm:gap-4">
		<svelte:element this={grouped ? 'h4' : 'h3'} class="font-medium wrap-anywhere {WORLD}">
			{#if id}
				<a href={bodyHref(id, name)} class="hover:underline underline-offset-2"><bdi>{name}</bdi></a
				>
			{:else}
				<bdi>{name}</bdi>
			{/if}
		</svelte:element>
		<ul class="flex min-w-0 flex-1 flex-col gap-2.5">
			{#each lines as row (row.key)}
				<li>
					{@render line(row)}
					{#if row.children}
						<ul class="mt-1.5 flex flex-col gap-1.5">
							{#each row.children as child (child.key)}
								<li>{@render line(child, true)}</li>
							{/each}
						</ul>
					{/if}
				</li>
			{/each}
		</ul>
	</div>
{/snippet}

<!-- The margin of the scroll keeps the heading clear of the table header. -->
{#snippet group(id: string, title: string)}
	<h3
		{id}
		class="mt-7 mb-1 scroll-mt-12 text-xs font-semibold uppercase tracking-wider text-muted-foreground"
	>
		{title}
	</h3>
{/snippet}

<div class="relative text-sm leading-relaxed">
	<PageContents entries={contents} />

	<p class="-mt-6 mb-2 text-xs text-muted-subtle">
		{m.status_generated({ date: formatIsoDate(data.generated_at) })}
	</p>
	<p class="mt-1.5 max-w-prose text-muted-foreground">{m.about_data_intro()}</p>

	<dl class="mt-6 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-6">
		{#each stats as stat (stat.label)}
			<div>
				<dt class="text-xs font-semibold uppercase tracking-wider text-muted-subtle">
					{stat.label}
				</dt>
				<dd class="text-xl tabular-nums">{stat.value}</dd>
			</div>
		{/each}
	</dl>

	{@render section('maps', m.about_data_maps(), m.about_data_maps_intro())}
	<div class={TABLE}>
		{@render header(
			true,
			m.about_data_column_map(),
			m.about_data_column_resolution(),
			m.about_data_column_tiles()
		)}
		{#each data.systems as system (system.id)}
			<section>
				{@render group(`maps-${system.id ?? 'other'}`, systemName(system))}
				{#each system.worlds as body (body.id)}
					{@render world(
						body.id,
						body.name,
						body.maps.map((map) => mapLine(body, map)),
						true
					)}
				{/each}
			</section>
		{/each}
	</div>

	{@render section('rings', m.tab_rings(), m.about_data_rings_intro())}
	<div class={TABLE}>
		{@render header(
			true,
			m.tab_rings(),
			m.about_data_column_resolution(),
			m.about_data_column_samples()
		)}
		{#each data.rings as body (body.id)}
			{@render world(
				body.id,
				body.name,
				body.rings.map((ring) => ringLine(body, ring))
			)}
		{/each}
	</div>

	{@render section('models', m.status_section_models(), m.about_data_models_intro())}
	<div id="models-worlds" class="{TABLE} scroll-mt-10">
		{@render header(true, m.about_data_column_model(), m.about_data_column_triangles(), '')}
		{#each data.models.worlds as body (body.id)}
			{@render world(body.id, body.name, body.models.map(shapeLine))}
		{/each}
		{#if data.models.lightcurve}
			{@render world(undefined, m.category_name_asteroids(), [
				lightcurveLine(data.models.lightcurve)
			])}
		{/if}
	</div>
	<div class={TABLE}>
		{@render header(false, m.about_data_column_model(), m.about_data_column_triangles(), '')}
		{#each data.models.craft as craft (craft.kind)}
			<section>
				{@render group(`models-${craft.kind}`, kindName(craft.kind))}
				{#each craftLines(craft) as row (row.key)}
					<div class="border-b border-border py-2.5">{@render line(row)}</div>
				{/each}
			</section>
		{/each}
	</div>
</div>
