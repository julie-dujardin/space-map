<!--
  Full-page panorama viewer for one body: `?at=` names the panorama, the
  arrows step along the traverse, and without `?at=` the page lists every
  panorama the body has.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import { MediaQuery } from 'svelte/reactivity';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import XIcon from '@lucide/svelte/icons/x';
	import Share2Icon from '@lucide/svelte/icons/share-2';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import {
		fetchObjectDetail,
		type ObjectDetailData,
		type PanoramaEntry
	} from '$lib/fetch/objects/object-data';
	import { meanRadiusKm } from '$lib/fetch/objects/physical';
	import { formatIsoDate } from '$lib/format/date';
	import { formatKm } from '$lib/format/distance';
	import { formatNumber } from '$lib/format/quantities';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import {
		findPanorama,
		panoramaAt,
		type Neighbour,
		type Neighbours
	} from '$lib/panorama/traverse';
	import { capitalize } from '$lib/search/format';
	import { shareUrl } from '$lib/share';
	import { panoramaHref } from '$lib/state/panorama-link';
	import { bodyHref, serializeUrl } from '$lib/state/url';
	import { DEFAULT_VIEW } from '$lib/state/view';
	import { urlTypeFromId } from '$lib/state/view';
	import { kmToScene } from '$lib/math/units';
	import { SimClock } from '$lib/scene/state/clock.svelte';
	import { fly } from 'svelte/transition';
	import { getSettings } from '$lib/state/settings.svelte';
	import { entryJd } from '$lib/panorama/minimap';
	import { PanoramaView, type ArrowKey, type ScreenAnchor } from '$lib/panorama/view';
	import PanoramaMinimap from './PanoramaMinimap.svelte';
	import PanoramaTimeline from './PanoramaTimeline.svelte';
	import PanoramaCreditBar from './PanoramaCreditBar.svelte';
	import SettingsButton from '../settings/SettingsButton.svelte';
	import PanoramaLayersButton from './PanoramaLayersButton.svelte';
	import type { LayerCredit } from '$lib/flatmap/layers';

	interface Props {
		bodyId: string;
	}

	let { bodyId }: Props = $props();

	let detail = $state<ObjectDetailData | null>(null);
	let detailError = $state(false);
	let textureState = $state<'loading' | 'ready' | 'error'>('loading');
	let container = $state<HTMLElement | null>(null);
	/** The view once its first panorama is on screen. */
	let view = $state<PanoramaView | null>(null);
	// The view's own state, mirrored so the chrome can follow it.
	let heading = $state(0);
	let fov = $state(75);
	let anchors = $state<Partial<Record<ArrowKey, ScreenAnchor>>>({});
	let angleGridVisible = $state(false);
	let navigationVisible = $state(true);
	let neighbours = $state.raw<Neighbours | null>(null);
	let timelineOpen = $state(false);
	/** The timeline strip only lays out beside the minimap from `md` up. */
	const wide = new MediaQuery('(min-width: 768px)');
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
	const radiusKm = $derived(meanRadiusKm(detail?.global ?? null) ?? 0);
	/** The arrows the view drew, each with the neighbour it points at. */
	const arrowTargets = $derived(
		(['previous', 'next'] as const).flatMap((key) => {
			const n = neighbours?.[key];
			return n && anchors[key] ? [{ key, n }] : [];
		})
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

	// One view per body. The panorama on screen follows the URL: the view
	// never steps on its own, it reports the arrow and the page navigates.
	$effect(() => {
		const opening = untrack(() => current);
		if (!container || !opening) return;
		const v = new PanoramaView({ body: bodyId, at: panoramaAt(opening), followArrows: false });
		v.mount(container);
		v.on('viewchange', (s) => {
			heading = s.heading;
			fov = s.fov;
		});
		v.on('arrows', (a) => (anchors = a));
		v.on('step', ({ entry }) => void goto(panoramaHref(bodyId, entry)));
		v.on('load', () => {
			textureState = 'ready';
			neighbours = v.getNeighbours();
		});
		v.on('error', (error) => {
			textureState = 'error';
			console.warn('Panorama:', error);
		});
		textureState = 'loading';
		let live = true;
		// Failures arrive on the error listener; the view opens `?at=` changes
		// only once it stands on its first panorama.
		v.load().then(
			() => {
				if (live) view = v;
			},
			() => {}
		);
		return () => {
			live = false;
			v.remove();
			view = null;
			neighbours = null;
		};
	});

	$effect(() => {
		if (!view || !current) return;
		const v = view;
		const entry = current;
		if (v.getCurrent()?.id === entry.id) return;
		textureState = 'loading';
		v.open(entry).catch(() => {});
		neighbours = v.getNeighbours();
	});

	$effect(() => {
		if (!wide.current) timelineOpen = false;
	});

	$effect(() => {
		if (current) clock.setJD(entryJd(current));
	});

	/** The traverse the current panorama belongs to. */
	const missionEntries = $derived(
		current ? entries.filter((e) => e.mission === current.mission) : []
	);

	$effect(() => {
		view?.setAngleGridVisible(angleGridVisible);
	});

	$effect(() => {
		view?.setArrowsVisible(navigationVisible);
	});

	/** A rover position to the metre, which three significant figures are not. */
	function formatCoordinate(deg: number): string {
		return `${deg.toLocaleString(getLocale(), { maximumFractionDigits: 5 })}${m.symbol_degree()}`;
	}

	function stepLabel(n: Neighbour): string {
		const sol = n.entry.sol !== undefined ? m.panorama_sol({ sol: n.entry.sol }) : '';
		return [sol, formatKm(n.distanceM / 1000)].filter(Boolean).join(' · ');
	}

	const pageTitle = $derived(
		current
			? [
					capitalize(current.mission ?? ''),
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
		return out;
	});

	const byMission = $derived.by(() => {
		const groups = new Map<string, PanoramaEntry[]>();
		for (const e of entries)
			groups.set(e.mission ?? '', [...(groups.get(e.mission ?? '') ?? []), e]);
		return [...groups.entries()];
	});

	/** Back to the map, standing over this panorama at its date; the body page
	 *  unframed when no panorama is open. */
	const closeHref = $derived(
		current && radiusKm
			? serializeUrl({
					...DEFAULT_VIEW,
					type: urlTypeFromId(bodyId),
					id: bodyId,
					name: bodyName,
					date: new Date(current.time),
					isNow: false,
					latitude: current.lat,
					longitude: current.lon,
					zoom: kmToScene(radiusKm) * 1.05,
					framed: true
				})
			: bodyHref(bodyId, bodyName)
	);

	const glassButton = `flex size-10 items-center justify-center rounded-full bg-black/40
		backdrop-blur-md transition-colors hover:bg-black/55 md:size-8`;
	const inBoxButton = `flex size-9 items-center justify-center rounded-md text-white/70
		transition-colors hover:bg-white/10 hover:text-white md:size-7`;
</script>

<svelte:head>
	<title>{pageTitle}</title>
</svelte:head>

<!-- Share then close, the order the detail drawer's button row uses. -->
{#snippet shareAndClose(buttonClass: string, iconClass: string)}
	<button
		type="button"
		onclick={() => shareUrl(pageTitle)}
		class="cursor-pointer {buttonClass}"
		aria-label={m.share()}
		title={m.share()}
	>
		<Share2Icon class={iconClass} />
	</button>
	<a href={closeHref} class={buttonClass} aria-label={m.close()} title={m.close()}>
		<XIcon class={iconClass} />
	</a>
{/snippet}

<Tooltip.Provider delayDuration={300}>
	<div class="fixed inset-0 bg-[#0b0d12] text-white">
		{#if current}
			<div bind:this={container} class="absolute inset-0 cursor-grab active:cursor-grabbing"></div>

			{#if navigationVisible}
				{#each arrowTargets as { key, n } (key)}
					{@const anchor = anchors[key]}
					{#if anchor?.visible}
						<a
							href={panoramaHref(bodyId, n.entry)}
							class="absolute -translate-x-1/2 -translate-y-[calc(100%+1.6rem)] rounded-full bg-black/55 px-2.5 py-1 text-xs whitespace-nowrap backdrop-blur-sm hover:bg-black/75"
							style="left:{anchor.x}px; top:{anchor.y}px"
							aria-label={key === 'previous' ? m.panorama_previous() : m.panorama_next()}
						>
							{stepLabel(n)}
						</a>
					{/if}
				{/each}
			{/if}

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
				<div class="flex items-start gap-2">
					<div class="min-w-0 flex-1">
						<a href={bodyHref(bodyId, bodyName)} class="text-xs text-white/60 hover:text-white">
							{bodyName}
						</a>
						<h1 class="text-base font-semibold leading-tight">
							{capitalize(current.mission ?? '')}
							{#if current.sol !== undefined}
								<span class="text-white/80">· {m.panorama_sol({ sol: current.sol })}</span>
							{/if}
						</h1>
						{#if current.title}
							<p class="text-xs text-white/70">{current.title}</p>
						{/if}
					</div>
					<div class="-mt-1 -me-1 flex shrink-0 items-center gap-0.5">
						{@render shareAndClose(inBoxButton, 'size-5 md:size-4')}
					</div>
				</div>
				<dl class="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
					{#each rows as row (row.label)}
						<dt class="text-white/55">{row.label}</dt>
						<dd>{row.value}</dd>
					{/each}
				</dl>
			</div>

			<!-- One row, so the minimap grows to the timeline's height. Nothing in
			     it stretches: the strip's measured height sets the minimap's, so a
			     stretched strip would measure its own output and ratchet up. -->
			{#if view && missionEntries.length}
				<div
					class="absolute bottom-[calc(var(--safe-bottom)_+_1.5rem)] start-[calc(var(--safe-start)_+_1rem)] end-[calc(var(--safe-end)_+_1rem)] flex items-end gap-2 {timelineOpen
						? ''
						: 'pointer-events-none'}"
				>
					<div class="pointer-events-auto shrink-0">
						<PanoramaMinimap
							{bodyId}
							entries={missionEntries}
							{current}
							{radiusKm}
							jd={clock.jd}
							headingDeg={heading}
							fovDeg={fov}
							expanded={timelineOpen}
							height={timelineOpen ? stripHeight : null}
							onToggle={() => (timelineOpen = wide.current && !timelineOpen)}
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
								missionName={capitalize(current.mission ?? '')}
								entries={missionEntries}
								{clock}
								href={(entry) => panoramaHref(bodyId, entry)}
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
							{capitalize(mission)}
							<span class="text-white/50">({formatNumber(list.length)})</span>
						</h2>
						<ul class="divide-y divide-white/10 text-sm">
							{#each list as e (e.id)}
								<li>
									<a
										href={panoramaHref(bodyId, e)}
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

		<!-- Menus. Close and share sit in the info box instead, which the list has
		     no equivalent of. -->
		<div
			class="absolute top-[calc(var(--safe-top)_+_1rem)] end-[calc(var(--safe-end)_+_1rem)] flex flex-col items-end gap-3"
		>
			{#if !current}
				{@render shareAndClose(glassButton, 'size-5 md:size-4')}
			{/if}
			<SettingsButton scope="panorama" />
			{#if current}
				<PanoramaLayersButton
					angleGrid={angleGridVisible}
					navigation={navigationVisible}
					onAngleGridChange={(visible) => (angleGridVisible = visible)}
					onNavigationChange={(visible) => (navigationVisible = visible)}
				/>
			{/if}
		</div>
	</div>
</Tooltip.Provider>
