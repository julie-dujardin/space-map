<!--
  Full-page panorama viewer for one body: `?at=` names the panorama, the
  arrows step along the traverse, and without `?at=` the page lists every
  panorama the body has.
-->
<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { toast } from 'svelte-sonner';
	import XIcon from '@lucide/svelte/icons/x';
	import Share2Icon from '@lucide/svelte/icons/share-2';
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import { siGithub } from 'simple-icons';
	import * as m from '$lib/paraglide/messages.js';
	import { GITHUB_REPO_URL } from '$lib/constants';
	import {
		fetchObjectDetail,
		type ObjectDetailData,
		type PanoramaEntry
	} from '$lib/fetch/objects/object-data';
	import { versionedUrl } from '$lib/fetch/data-base';
	import { formatIsoDate } from '$lib/format/date';
	import { formatKm } from '$lib/format/distance';
	import { formatNumber } from '$lib/format/quantities';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { isModifiedClick } from '$lib/modified-click';
	import {
		findPanorama,
		initialHeadingDeg,
		neighboursOf,
		panoramaHref,
		type Neighbour
	} from '$lib/panorama/traverse';
	import { bodyHref } from '$lib/state/url';
	import { safeHttpUrl } from '$lib/utils';
	import { PanoramaScene, type ArrowKey } from './panorama-scene.svelte';
	import PanoramaCompass from './PanoramaCompass.svelte';

	interface Props {
		bodyId: string;
	}

	let { bodyId }: Props = $props();

	let detail = $state<ObjectDetailData | null>(null);
	let detailError = $state(false);
	let textureState = $state<'loading' | 'ready' | 'error'>('loading');
	let container = $state<HTMLElement | null>(null);
	let scene = $state<PanoramaScene | null>(null);

	const at = $derived(page.url.searchParams.get('at'));
	const entries = $derived(detail?.global?.panoramas ?? []);
	const bodyName = $derived(detail?.localized?.name ?? detail?.global?.name ?? bodyId);
	const current = $derived(findPanorama(entries, at));
	const radiusKm = $derived.by(() => {
		const r = detail?.global?.radii;
		return r ? (r.a + r.b + r.c) / 3 : 0;
	});
	const neighbours = $derived(
		current && radiusKm ? neighboursOf(entries, current, radiusKm) : null
	);
	/** Neighbours far enough to walk toward; a repeat at the same spot has no
	 *  bearing and is reached from the info box instead. */
	const arrowTargets = $derived(
		(['previous', 'next'] as const)
			.map((key) => ({ key, n: neighbours?.[key] ?? null }))
			.filter((a): a is { key: ArrowKey; n: Neighbour } => !!a.n && a.n.distanceM >= 1)
	);

	$effect(() => {
		const id = bodyId;
		let cancelled = false;
		detail = null;
		detailError = false;
		fetchObjectDetail(id).then(
			(d) => {
				if (!cancelled) detail = d;
			},
			() => {
				if (!cancelled) detailError = true;
			}
		);
		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		if (!container || !current) return;
		const s = new PanoramaScene(container, (key) => {
			const n = neighbours?.[key];
			if (n) void goto(panoramaHref(bodyId, n.entry));
		});
		scene = s;
		return () => {
			s.dispose();
			scene = null;
		};
	});

	$effect(() => {
		if (!scene || !current) return;
		const s = scene;
		const entry = current;
		textureState = 'loading';
		s.setView(initialHeadingDeg(entry), 0);
		s.load(versionedUrl(`/v1/panoramas/${entry.id}.webp`, 'panoramas'), entry.north_offset_deg)
			.then(() => (textureState = 'ready'))
			.catch(() => (textureState = 'error'));
	});

	$effect(() => {
		scene?.setArrows(arrowTargets.map(({ key, n }) => ({ key, bearingDeg: n.bearingDeg })));
	});

	onDestroy(() => scene?.dispose());

	async function share() {
		const url = window.location.href;
		if (navigator.share) {
			try {
				await navigator.share({ url, title: pageTitle });
				return;
			} catch (err) {
				if ((err as DOMException).name === 'AbortError') return;
			}
		}
		try {
			await navigator.clipboard.writeText(url);
			toast.success(m.link_copied());
		} catch (err) {
			console.warn('Share failed:', err);
		}
	}

	/** A rover position to the metre, which three significant figures are not. */
	function formatCoordinate(deg: number): string {
		return `${deg.toLocaleString(getLocale(), { maximumFractionDigits: 5 })}${m.symbol_degree()}`;
	}

	function missionName(slug: string | undefined): string {
		return slug ? slug.charAt(0).toUpperCase() + slug.slice(1) : '';
	}

	function stepLabel(n: Neighbour): string {
		const sol = n.entry.sol !== undefined ? m.panorama_sol({ sol: n.entry.sol }) : '';
		const dist = n.distanceM >= 1 ? formatKm(n.distanceM / 1000) : m.panorama_same_spot();
		return [sol, dist].filter(Boolean).join(' · ');
	}

	function follow(e: MouseEvent, entry: PanoramaEntry) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		void goto(panoramaHref(bodyId, entry));
	}

	const pageTitle = $derived(
		current
			? [
					missionName(current.mission),
					current.sol !== undefined ? m.panorama_sol({ sol: current.sol }) : '',
					bodyName
				]
					.filter(Boolean)
					.join(' · ')
			: `${m.panorama_index_title()} · ${bodyName}`
	);

	const sweep = $derived(
		current && current.azimuth_start_deg !== undefined && current.hfov_deg !== undefined
			? {
					startDeg: current.azimuth_start_deg - current.north_offset_deg,
					widthDeg: current.hfov_deg
				}
			: null
	);
	const compassTicks = $derived(
		arrowTargets.map(({ key, n }) => ({
			bearingDeg: n.bearingDeg,
			label: `${key === 'previous' ? m.panorama_previous() : m.panorama_next()} · ${stepLabel(n)}`
		}))
	);

	/** Rows of the info box, in reading order. */
	const rows = $derived.by(() => {
		if (!current) return [];
		const out: Array<{ label: string; value: string }> = [];
		out.push({ label: m.panorama_date(), value: formatIsoDate(current.time) });
		if (current.instrument) out.push({ label: m.panorama_instrument(), value: current.instrument });
		out.push({ label: m.latitude(), value: formatCoordinate(current.lat) });
		out.push({ label: m.longitude(), value: formatCoordinate(current.lon) });
		if (current.elevation_m !== undefined)
			out.push({ label: m.panorama_elevation(), value: formatKm(current.elevation_m / 1000) });
		if (current.hfov_deg !== undefined && current.sphere_percent !== undefined)
			out.push({
				label: m.panorama_coverage(),
				value: m.panorama_coverage_value({
					degrees: formatNumber(Math.round(current.hfov_deg)),
					percent: formatNumber(Math.round(current.sphere_percent))
				})
			});
		if (current.color === 'grayscale')
			out.push({ label: m.panorama_imagery(), value: m.panorama_color_grayscale() });
		else if (current.color === 'rgb')
			out.push({ label: m.panorama_imagery(), value: m.panorama_color_rgb() });
		return out;
	});

	const byMission = $derived.by(() => {
		const groups = new Map<string, PanoramaEntry[]>();
		for (const e of entries)
			groups.set(e.mission ?? '', [...(groups.get(e.mission ?? '') ?? []), e]);
		return [...groups.entries()];
	});

	const sourceUrl = $derived(safeHttpUrl(current?.source_url));
	const creditUrl = $derived(safeHttpUrl(current?.credit_url));
</script>

<svelte:head>
	<title>{pageTitle}</title>
</svelte:head>

<div class="fixed inset-0 bg-[#0b0d12] text-white">
	{#if current}
		<div bind:this={container} class="absolute inset-0 cursor-grab active:cursor-grabbing"></div>

		{#each arrowTargets as { key, n } (key)}
			{@const anchor = scene?.anchors[key]}
			{#if anchor?.visible}
				<a
					href={panoramaHref(bodyId, n.entry)}
					onclick={(e) => follow(e, n.entry)}
					class="absolute -translate-x-1/2 -translate-y-[calc(100%+1.6rem)] rounded-full bg-black/55 px-2.5 py-1 text-xs whitespace-nowrap backdrop-blur-sm hover:bg-black/75"
					style="left:{anchor.x}px; top:{anchor.y}px"
					aria-label={key === 'previous' ? m.panorama_previous() : m.panorama_next()}
				>
					{stepLabel(n)}
				</a>
			{/if}
		{/each}

		{#if textureState !== 'ready'}
			<div
				class="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-white/70"
				aria-live="polite"
			>
				{textureState === 'loading' ? m.panorama_loading() : m.panorama_error()}
			</div>
		{/if}

		<!-- Info box -->
		<div
			class="absolute top-[calc(var(--safe-top)_+_1rem)] start-[calc(var(--safe-start)_+_1rem)] w-[min(20rem,calc(100vw-7.5rem))] rounded-md bg-black/40 p-3 text-sm backdrop-blur-sm"
		>
			<a href={bodyHref(bodyId, bodyName)} class="text-xs text-white/60 hover:text-white">
				{bodyName}
			</a>
			<h1 class="text-base font-semibold leading-tight">
				{missionName(current.mission)}
				{#if current.sol !== undefined}
					<span class="text-white/80">· {m.panorama_sol({ sol: current.sol })}</span>
				{/if}
			</h1>
			{#if current.title}
				<p class="text-xs text-white/70">{current.title}</p>
			{/if}
			<dl class="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
				{#each rows as row (row.label)}
					<dt class="text-white/55">{row.label}</dt>
					<dd>{row.value}</dd>
				{/each}
				{#if sourceUrl}
					<dt class="text-white/55">{m.panorama_source()}</dt>
					<dd>
						<a
							href={sourceUrl}
							target="_blank"
							rel="noopener noreferrer"
							class="inline-flex items-center gap-1 underline decoration-white/30 hover:decoration-white"
						>
							{current.id}
							<ExternalLinkIcon class="size-3" />
						</a>
					</dd>
				{/if}
			</dl>
			{#if neighbours}
				<nav class="mt-3 flex items-center justify-between gap-2 text-xs">
					{#if neighbours.previous}
						<a
							href={panoramaHref(bodyId, neighbours.previous.entry)}
							onclick={(e) => follow(e, neighbours!.previous!.entry)}
							class="inline-flex items-center gap-0.5 rounded px-1.5 py-1 hover:bg-white/10"
							aria-label={m.panorama_previous()}
						>
							<ChevronLeftIcon class="size-3.5" />
							{stepLabel(neighbours.previous)}
						</a>
					{:else}
						<span></span>
					{/if}
					{#if neighbours.next}
						<a
							href={panoramaHref(bodyId, neighbours.next.entry)}
							onclick={(e) => follow(e, neighbours!.next!.entry)}
							class="inline-flex items-center gap-0.5 rounded px-1.5 py-1 hover:bg-white/10"
							aria-label={m.panorama_next()}
						>
							{stepLabel(neighbours.next)}
							<ChevronRightIcon class="size-3.5" />
						</a>
					{/if}
				</nav>
			{/if}
		</div>

		<!-- Compass -->
		{#if scene}
			<div
				class="absolute bottom-[calc(var(--safe-bottom)_+_1rem)] start-[calc(var(--safe-start)_+_1rem)]"
			>
				<PanoramaCompass heading={scene.heading} fov={scene.fov} {sweep} ticks={compassTicks} />
			</div>
		{/if}

		<!-- Credit bar -->
		<div
			class="absolute bottom-[calc(var(--safe-bottom))] end-[var(--safe-end)] flex items-center rounded-s-sm bg-black/40 text-[11px] leading-tight text-white/75 backdrop-blur-sm whitespace-nowrap"
		>
			{#if current.credit}
				<span class="inline-block max-w-[60vw] truncate px-1 py-0 align-bottom">
					<span class="text-white/50">{m.attribution_imagery()}:</span>
					{#if creditUrl}
						<a
							href={creditUrl}
							target="_blank"
							rel="noopener noreferrer"
							class="hover:text-white transition-colors">{current.credit}</a
						>
					{:else}
						{current.credit}
					{/if}
				</span>
				<span class="text-white/40" aria-hidden="true">·</span>
			{/if}
			<a
				href={GITHUB_REPO_URL}
				target="_blank"
				rel="noopener noreferrer"
				class="flex items-center px-1 py-0 hover:text-white transition-colors"
				aria-label="GitHub"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="currentColor"
					class="h-3.5 w-3.5"
					aria-hidden="true"
				>
					<path d={siGithub.path} />
				</svg>
			</a>
		</div>
	{:else}
		<!-- html/body lock overflow for the 3D app, so the list owns its scroll. -->
		<main class="absolute inset-0 overflow-y-auto">
			<div class="mx-auto max-w-2xl px-4 py-[calc(var(--safe-top)_+_1rem)]">
				<a href={bodyHref(bodyId, bodyName)} class="text-xs text-white/60 hover:text-white">
					{bodyName}
				</a>
				<h1 class="mb-4 text-xl font-semibold">{m.panorama_index_title()}</h1>
				{#if detailError}
					<p class="text-sm text-white/70">{m.panorama_error()}</p>
				{:else if !detail}
					<p class="text-sm text-white/70">{m.loading()}</p>
				{:else if at}
					<p class="mb-4 text-sm text-white/70">{m.panorama_not_found()}</p>
				{/if}
				{#each byMission as [mission, list] (mission)}
					<h2 class="mt-4 mb-1 text-sm font-medium text-white/80">
						{missionName(mission)}
						<span class="text-white/50">({formatNumber(list.length)})</span>
					</h2>
					<ul class="divide-y divide-white/10 text-sm">
						{#each list as e (e.id)}
							<li>
								<a
									href={panoramaHref(bodyId, e)}
									onclick={(ev) => follow(ev, e)}
									class="flex items-baseline justify-between gap-3 py-1.5 hover:text-white text-white/85"
								>
									<span>
										{#if e.sol !== undefined}{m.panorama_sol({ sol: e.sol })}{/if}
										{#if e.title}<span class="text-white/60"> · {e.title}</span>{/if}
									</span>
									<span class="shrink-0 text-xs text-white/55">{formatIsoDate(e.time)}</span>
								</a>
							</li>
						{/each}
					</ul>
				{/each}
			</div>
		</main>
	{/if}

	<!-- Close and share -->
	<div
		class="absolute top-[calc(var(--safe-top)_+_1rem)] end-[calc(var(--safe-end)_+_1rem)] flex flex-col items-end gap-3"
	>
		<a
			href={bodyHref(bodyId, bodyName)}
			class="flex size-10 items-center justify-center rounded-full bg-black/40 backdrop-blur-md transition-colors hover:bg-black/55 md:size-8"
			aria-label={m.close()}
			title={m.close()}
		>
			<XIcon class="size-5 md:size-4" />
		</a>
		<button
			type="button"
			onclick={share}
			class="flex size-10 cursor-pointer items-center justify-center rounded-full bg-black/40 backdrop-blur-md transition-colors hover:bg-black/55 md:size-8"
			aria-label={m.share()}
			title={m.share()}
		>
			<Share2Icon class="size-5 md:size-4" />
		</button>
	</div>
</div>
