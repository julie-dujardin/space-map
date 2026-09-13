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
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
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
	import { SimClock } from '$lib/scene/state/clock.svelte';
	import { fly } from 'svelte/transition';
	import { getSettings } from '$lib/state/settings.svelte';
	import { entryJd } from '$lib/panorama/minimap';
	import { PanoramaScene, type ArrowKey } from './panorama-scene.svelte';
	import PanoramaMinimap from './PanoramaMinimap.svelte';
	import PanoramaTimeline from './PanoramaTimeline.svelte';
	import PanoramaCreditBar from './PanoramaCreditBar.svelte';
	import type { LayerCredit } from '$lib/flatmap/layers';

	interface Props {
		bodyId: string;
	}

	let { bodyId }: Props = $props();

	let detail = $state<ObjectDetailData | null>(null);
	let detailError = $state(false);
	let textureState = $state<'loading' | 'ready' | 'error'>('loading');
	let container = $state<HTMLElement | null>(null);
	let scene = $state<PanoramaScene | null>(null);
	let timelineOpen = $state(false);
	let mapCredits = $state<LayerCredit[]>([]);
	/** The strip's height, which the map beside it grows to. Kept from the last
	 *  opening so the next one animates straight to size. */
	let stripHeight = $state(208);
	const motionMs = $derived(getSettings().resolvedReducedMotion ? 0 : 250);

	// The viewer's own clock: it stands on the panorama being looked at, and the
	// timeline scrubs it from there.
	const clock = new SimClock(0);

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
		if (current) clock.setJD(entryJd(current));
	});

	/** The traverse the current panorama belongs to. */
	const missionEntries = $derived(
		current ? entries.filter((e) => e.mission === current.mission) : []
	);

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
</script>

<svelte:head>
	<title>{pageTitle}</title>
</svelte:head>

<Tooltip.Provider delayDuration={300}>
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
				</dl>
			</div>

			<!-- Traverse minimap and, when opened, the timeline beside it. One row,
			     so the two share a height: the strip's content sets it and the
			     map stretches to match. -->
			{#if scene && missionEntries.length}
				<div
					class="absolute bottom-[calc(var(--safe-bottom)_+_1.5rem)] start-[calc(var(--safe-start)_+_1rem)] end-[calc(var(--safe-end)_+_1rem)] flex items-stretch gap-2 {timelineOpen
						? ''
						: 'pointer-events-none'}"
				>
					<div class="pointer-events-auto shrink-0 self-end">
						<PanoramaMinimap
							{bodyId}
							entries={missionEntries}
							{current}
							{radiusKm}
							jd={clock.jd}
							headingDeg={scene.heading}
							fovDeg={scene.fov}
							expanded={timelineOpen}
							height={timelineOpen ? stripHeight : null}
							onToggle={() => (timelineOpen = !timelineOpen)}
							onCredits={(credits) => (mapCredits = credits)}
							onPick={(entry) => void goto(panoramaHref(bodyId, entry))}
						/>
					</div>
					{#if timelineOpen}
						<div
							class="min-w-0 flex-1"
							bind:clientHeight={stripHeight}
							transition:fly={{ y: 12, duration: motionMs }}
						>
							<PanoramaTimeline
								missionName={missionName(current.mission)}
								entries={missionEntries}
								{clock}
								onPick={(entry) => void goto(panoramaHref(bodyId, entry))}
								onClose={() => (timelineOpen = false)}
								positionClass="relative"
							/>
						</div>
					{/if}
				</div>
			{/if}

			<!-- Credit bar -->
			<div class="absolute bottom-[var(--safe-bottom)] end-[var(--safe-end)]">
				<PanoramaCreditBar entry={current} {mapCredits} />
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
</Tooltip.Provider>
