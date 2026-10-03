<!--
  Full-page panorama viewer for one body: `?at=` names the panorama and the
  arrows step along the traverse. Without `?at=` the page is the body's own
  gallery — the same traverse cards the gallery of every world draws, since a
  world with hundreds of stops has no list worth reading.
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
		isViewable,
		type ObjectDetailData
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
	import { bodyTraverses } from '$lib/panorama/traverses';
	import { gyroAvailability } from '$lib/panorama/gyro';
	import { PanoramaView, type ArrowKey, type ScreenAnchor } from '$lib/panorama/view';
	import PanoramaMinimap from './PanoramaMinimap.svelte';
	import TraverseCards from './TraverseCards.svelte';
	import MapCredits from './MapCredits.svelte';
	import PanoramaTimeline from './PanoramaTimeline.svelte';
	import PanoramaCreditBar from './PanoramaCreditBar.svelte';
	import SiteMenuButton from '../nav/SiteMenuButton.svelte';
	import SitePage from '../nav/SitePage.svelte';
	import PanoramaGyroButton from './PanoramaGyroButton.svelte';
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
	/** Whether the sensor is turning the view right now, which is the standing
	 *  preference except where the device refused it. */
	let gyroActive = $state(false);
	const gyroSupported = gyroAvailability() === 'available';
	let neighbours = $state.raw<Neighbours | null>(null);
	let timelineOpen = $state(false);
	/** From `md` up the timeline lays out beside the minimap. */
	const wide = new MediaQuery('(min-width: 768px)');
	/** Below that there is no room beside it: the open timeline takes the
	 *  whole screen, panorama included. */
	const covering = $derived(timelineOpen && !wide.current);
	let mapCredits = $state<LayerCredit[]>([]);
	/** The strip's height, which the map beside it grows to. Kept from the last
	 *  opening so the next one animates straight to size. */
	let stripHeight = $state(208);
	const motionMs = $derived(getSettings().resolvedReducedMotion ? 0 : 250);

	// The viewer's own clock: it stands on the panorama being looked at, and the
	// timeline scrubs it from there.
	const clock = new SimClock(0);

	const at = $derived(page.url.searchParams.get('at'));
	// A stop whose imagery is withheld has no sphere to open: the map draws
	// it as a place, and this page lists and opens nothing there.
	const entries = $derived((detail?.global?.panoramas ?? []).filter(isViewable));
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

	// The standing preference, applied to each view as it opens. iOS grants the
	// sensor only inside the gesture that asks, so this quietly does nothing
	// there until the button is pressed.
	$effect(() => {
		const v = view;
		const wanted = gyroSupported && getSettings().resolvedPanoramaGyro;
		if (!v) return;
		void v.setGyroEnabled(wanted).then((on) => (gyroActive = on));
	});

	/** The sensor may be refused, so the button follows what the view reports. */
	async function toggleGyro() {
		const wanted = !gyroActive;
		getSettings().setPanoramaGyro(wanted ? 'on' : 'off');
		gyroActive = (await view?.setGyroEnabled(wanted)) ?? false;
	}

	/** A rover position to the metre, which three significant figures are not. */
	function formatCoordinate(deg: number): string {
		return `${deg.toLocaleString(getLocale(), { maximumFractionDigits: 5 })}${m.symbol_degree()}`;
	}

	function stepLabel(n: Neighbour): string {
		const sol = n.entry.sol !== undefined ? m.panorama_sol({ sol: n.entry.sol }) : '';
		return [sol, formatKm(n.distanceM / 1000)].filter(Boolean).join(' · ');
	}

	/** What the panorama is called: the craft, and the sol where it counts them. */
	const caption = $derived(
		current
			? [
					capitalize(current.mission ?? ''),
					current.sol !== undefined ? m.panorama_sol({ sol: current.sol }) : ''
				]
					.filter(Boolean)
					.join(' · ')
			: ''
	);

	const pageTitle = $derived(
		current
			? [caption, bodyName].filter(Boolean).join(' · ')
			: `${m.panorama_index_title()} · ${bodyName}`
	);

	/** Rows of the info column, in reading order. */
	const rows = $derived.by(() => {
		if (!current) return [];
		/** `long`: a value that needs the row to itself where the rows pair up. */
		const out: Array<{ label: string; value: string; long?: boolean }> = [];
		out.push({ label: m.panorama_date(), value: formatIsoDate(current.time) });
		if (current.instrument) out.push({ label: m.panorama_instrument(), value: current.instrument });
		out.push({ label: m.latitude(), value: formatCoordinate(current.lat) });
		out.push({ label: m.longitude(), value: formatCoordinate(current.lon) });
		if (current.elevation_m !== undefined)
			out.push({ label: m.panorama_elevation(), value: formatKm(current.elevation_m / 1000) });
		if (current.altitude_m !== undefined)
			out.push({ label: m.panorama_altitude(), value: formatKm(current.altitude_m / 1000) });
		if (current.hfov_deg !== undefined && current.sphere_percent !== undefined)
			out.push({
				label: m.panorama_coverage(),
				value: m.panorama_coverage_value({
					degrees: formatNumber(Math.round(current.hfov_deg)),
					percent: formatNumber(Math.round(current.sphere_percent))
				}),
				long: true
			});
		return out;
	});

	/** The body's traverses, named by the craft that drove them — awaited by the
	 *  gallery, so it says it is loading rather than saying it is empty. Asked
	 *  for only where the page is the gallery: with a panorama open there is
	 *  nothing to draw them on. */
	const traverses = $derived(at || !detail ? null : bodyTraverses(bodyId, entries));
	/** What the cards' maps are drawn from, credited once under them. */
	let galleryCredits = $state<LayerCredit[]>([]);

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

	function toggleTimeline(): void {
		timelineOpen = !timelineOpen;
	}

	/** The minimap and the timeline: a row along the bottom, or the whole
	 *  screen as a column with the map last. */
	const dockClass = $derived(
		covering
			? `bg-background/90 text-foreground absolute inset-0 flex flex-col-reverse gap-4
				ps-[calc(var(--safe-start)_+_1rem)] pe-[calc(var(--safe-end)_+_1rem)]
				pt-[calc(var(--safe-top)_+_4.5rem)] pb-[calc(var(--safe-bottom)_+_1.5rem)] backdrop-blur-lg`
			: `absolute bottom-[calc(var(--safe-bottom)_+_1.5rem)] start-[calc(var(--safe-start)_+_1rem)]
				end-[calc(var(--safe-end)_+_1rem)] flex items-end gap-2 ${timelineOpen ? '' : 'pointer-events-none'}`
	);

	/** The glass of the menu buttons, for the two beside them that open nothing. */
	const glassButton = `flex size-10 cursor-pointer items-center justify-center rounded-full
		bg-black/40 text-white backdrop-blur-md transition-colors hover:bg-black/55 md:size-8`;
</script>

<svelte:head>
	<title>{pageTitle}</title>
</svelte:head>

{#if current}
	<!-- What the panorama is, in full: the timeline's first column, or the
	     head of the screen where the timeline covers it. -->
	{#snippet about()}
		<div class="flex flex-col gap-2.5">
			<div>
				<h1 class={covering ? 'text-base font-semibold' : 'text-sm font-medium'}>{caption}</h1>
				{#if current?.title}
					<p class="text-muted-foreground text-xs">{current.title}</p>
				{/if}
			</div>
			<!-- Covering, the rows pair up: every line saved goes to the map. -->
			<dl
				class="grid gap-x-3 gap-y-0.5 text-xs {covering
					? 'grid-cols-[auto_auto_auto_1fr]'
					: 'grid-cols-[auto_1fr]'}"
			>
				{#each rows as row (row.label)}
					<dt class="text-muted-foreground {covering && row.long ? 'col-start-1' : ''}">
						{row.label}
					</dt>
					<dd class={covering && row.long ? 'col-span-3' : ''}>{row.value}</dd>
				{/each}
			</dl>
			<a
				href="/view"
				class="text-muted-foreground hover:text-foreground self-start text-xs hover:underline"
			>
				{m.panorama_index_all()}
			</a>
		</div>
	{/snippet}

	<Tooltip.Provider delayDuration={300}>
		<div class="fixed inset-0 bg-[#0b0d12] text-white">
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

			<!-- As a row, the minimap grows to the timeline's height. Nothing in it
			     stretches: the strip's measured height sets the minimap's, so a
			     stretched strip would measure its own output and ratchet up. As a
			     column the map takes what the timeline leaves. -->
			{#if missionEntries.length}
				<div class={dockClass}>
					<div
						class="pointer-events-auto overflow-hidden rounded-md {covering
							? 'min-h-24 flex-1'
							: 'min-w-44 shrink-0'}"
					>
						<!-- The name rides on the map while the timeline is shut; open, the
						     strip's first column says it in full. `w-0 min-w-full`: the map
						     sets the width, a long title does not. -->
						{#if !timelineOpen}
							<h1>
								<button
									type="button"
									onclick={toggleTimeline}
									title={m.panorama_map_expand()}
									class="block w-0 min-w-full cursor-pointer bg-black/40 px-2.5 py-1.5 text-start backdrop-blur-sm"
								>
									<span class="block truncate text-sm leading-tight font-semibold">{caption}</span>
									{#if current.title}
										<span class="block truncate text-xs font-normal text-white/70">
											{current.title}
										</span>
									{/if}
								</button>
							</h1>
						{/if}
						{#if view}
							<PanoramaMinimap
								{bodyId}
								entries={missionEntries}
								{current}
								{radiusKm}
								jd={clock.jd}
								headingDeg={heading}
								fovDeg={fov}
								expanded={timelineOpen}
								fill={covering}
								height={timelineOpen ? stripHeight : null}
								onToggle={toggleTimeline}
								onCredits={(credits) => (mapCredits = credits)}
								onPick={(entry) => void goto(panoramaHref(bodyId, entry))}
							/>
						{/if}
					</div>
					{#if timelineOpen}
						<div
							class={covering ? '' : 'min-w-0 flex-1'}
							bind:clientHeight={stripHeight}
							transition:fly={{ y: 12, duration: motionMs }}
						>
							<PanoramaTimeline
								aside={about}
								bare={covering}
								entries={missionEntries}
								{clock}
								href={(entry) => panoramaHref(bodyId, entry)}
								onPick={(entry) => void goto(panoramaHref(bodyId, entry))}
								onClose={covering ? undefined : () => (timelineOpen = false)}
								positionClass="relative"
								activeId={current.id}
							/>
						</div>
					{/if}
				</div>
			{/if}

			<!-- Credit bar -->
			<div class="absolute bottom-[var(--safe-bottom)] end-[var(--safe-end)]">
				<PanoramaCreditBar entry={current} {mapCredits} />
			</div>

			<!-- Leaving and sharing, opposite the menus. Over a covered panorama the
			     cross takes the cover away: a reader who meant that stays in the view. -->
			<div
				class="absolute top-[calc(var(--safe-top)_+_1rem)] start-[calc(var(--safe-start)_+_1rem)] flex gap-3"
			>
				{#if covering}
					<button
						type="button"
						onclick={() => (timelineOpen = false)}
						class={glassButton}
						aria-label={m.panorama_map_collapse()}
						title={m.panorama_map_collapse()}
					>
						<XIcon class="size-5 md:size-4" />
					</button>
				{:else}
					<a href={closeHref} class={glassButton} aria-label={m.close()} title={m.close()}>
						<XIcon class="size-5 md:size-4" />
					</a>
				{/if}
				<button
					type="button"
					onclick={() => shareUrl(pageTitle)}
					class={glassButton}
					aria-label={m.share()}
					title={m.share()}
				>
					<Share2Icon class="size-5 md:size-4" />
				</button>
			</div>

			<div
				class="absolute top-[calc(var(--safe-top)_+_1rem)] end-[calc(var(--safe-end)_+_1rem)] flex flex-col items-end gap-3"
			>
				<SiteMenuButton current="panoramas" scope="panorama" />
				<!-- These act on the panorama, which a covering timeline hides. -->
				{#if !covering}
					<PanoramaLayersButton
						angleGrid={angleGridVisible}
						navigation={navigationVisible}
						onAngleGridChange={(visible) => (angleGridVisible = visible)}
						onNavigationChange={(visible) => (navigationVisible = visible)}
					/>
					{#if gyroSupported}
						<PanoramaGyroButton active={gyroActive} onToggle={() => void toggleGyro()} />
					{/if}
				{/if}
			</div>
		</div>
	</Tooltip.Provider>
{:else}
	<!-- The gallery is a document page, not a view of the body: it carries the
	     same frame as the gallery of every world, and the map is one tab away. -->
	<SitePage current="panoramas" title={m.panorama_index_title()}>
		<!-- The body sits where the gallery puts it: a section heading under the
		     title, not a breadcrumb over it. -->
		<h2 class="mb-3 text-lg font-medium">{bodyName}</h2>

		{#if detailError}
			<p class="text-sm text-muted-foreground">{m.panorama_error()}</p>
		{:else if at}
			<p class="mb-4 text-sm text-muted-foreground">{m.panorama_not_found()}</p>
		{:else if traverses}
			{#await traverses}
				<p class="text-sm text-muted-foreground">{m.loading()}</p>
			{:then found}
				{#if found.length}
					<TraverseCards
						{bodyId}
						{radiusKm}
						traverses={found}
						onCredits={(l) => (galleryCredits = l)}
					/>
					<MapCredits credits={galleryCredits} class="mt-8" />
				{:else}
					<p class="text-sm text-muted-foreground">{m.panorama_gallery_empty()}</p>
				{/if}
			{/await}
		{:else}
			<p class="text-sm text-muted-foreground">{m.loading()}</p>
		{/if}
	</SitePage>
{/if}
