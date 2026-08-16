<!--
  The sidebar shell the travel panel lives in on `/nav/<from>/<to>`.

  It mirrors DetailDrawer's frame — Vaul sheet on mobile, fixed aside on desktop
  — but has no tabs: a trip is one panel, and its two ends are the URL rather
  than a selection inside the app.
-->
<script lang="ts">
	import { getContext, onMount, untrack } from 'svelte';
	import { Drawer as Vaul } from 'vaul-svelte';
	import { Button } from '$lib/components/ui/button/index.js';
	import { ScrollArea } from '$lib/components/ui/scroll-area/index.js';
	import XIcon from '@lucide/svelte/icons/x';
	import Share2Icon from '@lucide/svelte/icons/share-2';
	import { toast } from 'svelte-sonner';
	import * as m from '$lib/paraglide/messages.js';
	import type { BodyData } from '$lib/types/objects';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { AppState } from '$lib/state/app-state.svelte';
	import { fetchObjectDetail, type GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import { CAT_SOLAR_SYSTEM } from '$lib/fetch/groups/registry';
	import type { TimelineEntry } from '$lib/travel/timeline';
	import type { Hazard } from '$lib/travel/hazards';
	import type { LabelledPath } from '$lib/travel/labelled-path';
	import type { TrajectoryFrame } from '$lib/math/travel';
	import { lookupIn, transferPlan } from '$lib/travel/travel-body';
	import { DEFAULT_TRIP } from '$lib/travel/trip';
	import { resolveTripBodies } from '$lib/travel/resolve';
	import { ASSIST_BODY_IDS } from '$lib/travel/assist-bodies';
	import { fetchBodyNomenclature } from '$lib/fetch/nomenclature/fetch';
	import type { EndSite, TravelEndpointPick } from '$lib/travel/endpoint';
	import { fetchLaunchPads, padAt, type LaunchPad } from '$lib/travel/launch-pad';
	import type { NavPlace } from '$lib/state/view';
	import { navEndOf, type NavEnd } from '$lib/state/url';
	import { landedEnd, type LandedEnd } from '$lib/travel/probe-end';
	import type { Crumb } from '$lib/state/breadcrumb';
	import DrawerTitle from '../frame/DrawerTitle.svelte';
	import { routeLabel } from './route-labels';
	import TravelPanel from './TravelPanel.svelte';

	interface Props {
		/** Departure and destination ids, straight off the route. Either is null
		 *  when that end has not been chosen. */
		fromId: string | null;
		toId: string | null;
		/** IAU feature ids when an end is a named place on its body's surface. */
		fromFeatureId: number | null;
		toFeatureId: number | null;
		/** Bare coordinates when an end is a place nothing names — a launch pad. */
		fromPlace: NavPlace | null;
		toPlace: NavPlace | null;
		/** The app's clock, as a Julian Date. Live — see `nowJd` below. */
		clockJd: number;
		isMobile: boolean;
		/** Which frame the map draws the trip's ends in — the map's own control
		 *  owns it; this only carries it through to the solve. */
		viewFrame: TrajectoryFrame;
		inert?: boolean;
		onClose: () => void;
		/** How much of the viewport the mobile sheet covers, so the map's floating
		 *  controls can get out of its way. */
		onSheetResize?: (heightDvh: number) => void;
		/** The trajectory being read, labelled at both ends, for the scene to draw;
		 *  null when there is none. */
		onPathChange: (plan: LabelledPath | null) => void;
		/** The trajectories still on offer, for the scene to draw behind it; empty
		 *  once one of them is being read. */
		onOptionsChange: (options: readonly LabelledPath[]) => void;
		/** Which trajectory the reader is pointing at; null when none. */
		onHoverChange: (id: string | null) => void;
		/** The same trajectory as its legs, for the timeline under the map. */
		onTimelineChange: (entries: TimelineEntry[] | null) => void;
		/** What that trajectory puts the craft through, for the map to band it with. */
		onHazardsChange: (hazards: readonly Hazard[]) => void;
	}
	let {
		fromId,
		toId,
		fromFeatureId,
		toFeatureId,
		fromPlace,
		toPlace,
		clockJd,
		isMobile,
		viewFrame,
		inert = false,
		onClose,
		onSheetResize,
		onPathChange,
		onOptionsChange,
		onHoverChange,
		onTimelineChange,
		onHazardsChange
	}: Props = $props();

	// The planner reasons from a "now" captured when the trip opens, not from the
	// live clock: the clock ticks twice a second and each tick would re-solve a
	// whole porkchop grid. Choosing a different date is what "depart at" is for.
	//
	// Reading the clock under `untrack` is not enough on its own. The ends are
	// read off the app's view object, which is *replaced* on every clock tick, so
	// anything that touches them is marked stale twice a second and re-samples the
	// clock when it next runs. The key is what stops that: a string that only
	// changes when the ends do, and a derived that compares by value.
	let endsKey = $derived(`${fromId}|${toId}`);
	let nowJd = $state(untrack(() => clockJd));
	$effect(() => {
		void endsKey;
		untrack(() => (nowJd = clockJd));
	});

	const ctx = getContext<ContextManager | undefined>('ctx');
	const appState = getContext<AppState | undefined>('appState');

	// Read off the view rather than taken as a prop: the ends come down from the
	// page because the scene needs them too, but the terms are the panel's alone.
	let trip = $derived(appState?.view.trip ?? DEFAULT_TRIP);

	// The two ends and their chains up to the Sun. Deliberately not derived from
	// the scene: a trip end is any object in the catalogue, and most of them are
	// nowhere near what is being drawn. Resolution is keyed on the ids alone —
	// re-running it as bodies stream in would hand the panel a fresh map on every
	// bump and re-solve the grid for nothing.
	let tripBodies = $state(new Map<string, BodyData>());
	let resolving = $state(true);

	// What the scene already holds, as a row the kernel can use. A probe's chunk
	// carries sampled positions rather than elements, so its own row is zeroed and
	// the osculating fit beside it is what describes the orbit; returning null
	// sends the resolver to the catalogue instead.
	function residentBody(id: string): BodyData | null {
		const found = ctx?.getBody(id);
		if (!found) return null;
		if (found.data.a > 0) return found.data;
		const elements = found.orbitElements ?? found.rederiveElements?.(nowJd) ?? null;
		return elements ? { ...found.data, ...elements } : null;
	}

	/**
	 * One end read again at a date the search has reached, when the row in hand
	 * does not describe it there.
	 *
	 * A planet's ellipse is good for centuries. A probe's is a fit over the weeks
	 * its chunk covers, so a transfer arriving years later is aimed by an ellipse
	 * that expired long before. Nothing comes back for a probe that goes round
	 * another primary by then: elements about a different centre are not a
	 * correction to these, they are a different trip.
	 */
	async function refineBody(id: string, jd: number): Promise<BodyData | null> {
		const found = ctx?.getBody(id);
		const rederive = found?.rederiveElements;
		if (!found || !rederive) return null;
		if (jd >= found.data.validityStart && jd <= found.data.validityEnd) return null;

		const store = ctx?.probeStore;
		if (store && id.startsWith('probe-')) {
			await store.warmAt(jd);
			const there = store.probeWithCenter(id, jd);
			if (!there) {
				console.debug(
					`[travel] ${id} has no fit covering the trip's own dates — keeping the last.`
				);
				return null;
			}
			const here = store.probeWithCenter(id, nowJd);
			if (here && here.fitCenterNaifId !== there.fitCenterNaifId) {
				console.debug(
					`[travel] ${id} goes round naif-${there.fitCenterNaifId} by then, not this trip.`
				);
				return null;
			}
		}
		const elements = rederive(jd);
		return elements ? { ...found.data, ...elements } : null;
	}

	/**
	 * Each end as a probe parked on a surface, when that is what it is.
	 *
	 * A landed probe is a place rather than a body: it has no orbit of its own,
	 * and the trip is flown to the body holding it. So the end is swapped for its
	 * host here, once, and the probe survives as the site the arc reaches — which
	 * is exactly what a named crater already does.
	 */
	let fromLanded = $state.raw<LandedEnd | null>(null);
	let toLanded = $state.raw<LandedEnd | null>(null);

	/** Where a probe is parked. Nothing else has a place to be, so nothing else
	 *  costs a fetch. */
	async function locateEnd(id: string | null): Promise<LandedEnd | null> {
		if (id === null || !id.startsWith('probe-')) return null;
		const store = ctx?.probeStore;
		if (!store) return null;
		// The renderer warms this window every frame, so only a cold deep link
		// waits on a fetch this started.
		await store.ensure(nowJd).done;
		return landedEnd(store, id, nowJd);
	}

	$effect(() => {
		const ends = [fromId, toId];
		let cancelled = false;
		resolving = true;
		void (async () => {
			const [from, to] = await Promise.all(ends.map(locateEnd));
			if (cancelled) return;
			fromLanded = from;
			toLanded = to;
			// The swing-by candidates ride along with the trip's own ends. They are the
			// planets, so the scene almost always has them already, and the resolver
			// caches for the session — asking for them costs a walk, not a fetch.
			const ids = [
				...[from?.hostId ?? ends[0], to?.hostId ?? ends[1]].filter((id) => id !== null),
				...ASSIST_BODY_IDS
			];
			// Untracked: `residentBody` runs synchronously inside the resolver and reads
			// the scene, which moves. Without this the effect depends on every body it
			// asked about and re-runs as they do — a fresh map, a fresh solve, forever.
			// The ids above are the whole dependency, which is what the comment on
			// `tripBodies` claims and what only held while the ends were the only ones
			// looked up.
			const bodies = await untrack(() => resolveTripBodies(ids, residentBody));
			if (cancelled) return;
			// An end that resolved once is kept when a later pass cannot find it: the
			// scene's index is momentarily empty while it rebuilds, and a pass that
			// lands in that window would otherwise drop a body the trip is built on
			// and take the whole panel down with it.
			for (const [id, body] of tripBodies) {
				if (ids.includes(id) && !bodies.has(id)) bodies.set(id, body);
			}
			tripBodies = bodies;
			resolving = false;
		})();
		return () => {
			cancelled = true;
		};
	});

	/** The body each end is priced against: the host when the end is parked on
	 *  one, else the end itself. */
	let originId = $derived(fromLanded?.hostId ?? fromId);
	let targetId = $derived(toLanded?.hostId ?? toId);

	let origin = $derived(originId === null ? null : (tripBodies.get(originId) ?? null));
	let target = $derived(targetId === null ? null : (tripBodies.get(targetId) ?? null));

	/** Where on its body each end sits, for the panel to aim the ground leg at. */
	let originSite = $derived<EndSite | null>(siteOf(fromLanded, fromFeatureId, fromPlace));
	let targetSite = $derived<EndSite | null>(siteOf(toLanded, toFeatureId, toPlace));

	function siteOf(
		landed: LandedEnd | null,
		featureId: number | null,
		place: NavPlace | null
	): EndSite | null {
		if (landed) return { kind: 'point', latDeg: landed.latDeg, lonDeg: landed.lonDeg };
		if (place) return { kind: 'point', latDeg: place.latDeg, lonDeg: place.lonDeg };
		return featureId === null ? null : { kind: 'feature', featureId };
	}

	/**
	 * Whether the panel has ever had an origin to show.
	 *
	 * Once it has, it stays mounted whatever happens to the lookup afterwards. It
	 * owns state that cannot be rebuilt from anywhere — which endpoint box is
	 * open, the solved grid, a hand-picked trajectory — and unmounting it silently
	 * throws all of that away, including a click still in progress over it. It
	 * says why it is stuck better than this branch can anyway.
	 */
	let resolvedOnce = $state(false);
	$effect(() => {
		if (origin || fromId === null) resolvedOnce = true;
	});

	// Bodies to test the search results against. The scene's own, since only
	// something already loaded can be compared cheaply — see `excluded` below.
	let sceneBodies = $derived.by((): Map<string, BodyData> => {
		void ctx?.bodies.minorBodyVersion;
		const out = new Map<string, BodyData>();
		if (!ctx) return out;
		for (const [id, body] of ctx.bodies.bodiesById) out.set(id, body.data);
		return out;
	});

	// Localized planet names come from the solar-system category's member map —
	// one cached fetch for the whole dropdown, instead of a localized object
	// bundle per candidate.
	let names = $state<Record<string, string>>({});
	$effect(() => {
		let cancelled = false;
		fetchGroupDetail(CAT_SOLAR_SYSTEM)
			.then((d) => {
				if (!cancelled) names = d.localized?.notable_member_names ?? {};
			})
			.catch((e) => console.warn('[travel] no localized body names, falling back to export:', e));
		return () => {
			cancelled = true;
		};
	});

	function displayName(body: BodyData): string {
		return names[body.id] ?? body.name ?? body.id;
	}

	// Bodies the search must not offer for one end, given what the other end is.
	// Only the loaded bodies can be tested up front — the index reaches far past
	// the scene — so this catches the two cases that actually come up (the same
	// body twice, and a moon of the other end's own primary) and leaves the rest
	// to the panel, which now says why once the pick resolves.
	function excluded(against: BodyData | null): ReadonlySet<string> {
		const out = new Set<string>();
		if (!against) return out;
		out.add(against.id);
		const lookup = lookupIn(sceneBodies);
		for (const b of sceneBodies.values()) {
			if (transferPlan(b, against, lookup).kind === 'blocked') out.add(b.id);
		}
		return out;
	}

	let excludeForOrigin = $derived(excluded(target));
	let excludeForTarget = $derived(excluded(origin));

	// A feature endpoint is labelled by the place, not by the planet under it.
	// Resolved from the body's nomenclature so a shared link reads correctly on
	// load, when no pick handed us a name.
	let featureNames = $state<Record<string, string>>({});

	function loadFeatureName(bodyId: string, featureId: number | null) {
		if (featureId === null) return;
		const key = `${bodyId}:${featureId}`;
		if (featureNames[key]) return;
		let cancelled = false;
		fetchBodyNomenclature(bodyId)
			.then((features) => {
				const found = features.find((f) => f.featureId === featureId);
				if (cancelled) return;
				if (!found) {
					console.warn(`[travel] feature ${featureId} is not in ${bodyId}'s nomenclature.`);
					return;
				}
				featureNames = { ...featureNames, [key]: found.name };
			})
			.catch((e) => console.warn(`[travel] could not name feature ${featureId} on ${bodyId}:`, e));
		return () => {
			cancelled = true;
		};
	}

	$effect(() => {
		if (fromId === null) return;
		return loadFeatureName(fromId, fromFeatureId);
	});
	$effect(() => {
		if (toId === null) return;
		return loadFeatureName(toId, toFeatureId);
	});

	// A probe parked on a surface is labelled by the probe rather than by the
	// planet under it: the trip is to Mars 6, which happens to be at Mars.
	let landedNames = $state<Record<string, string>>({});
	function loadLandedName(id: string | null, landed: LandedEnd | null) {
		if (id === null || !landed || landedNames[id]) return;
		let cancelled = false;
		fetchObjectDetail(id, false)
			.then((d) => {
				const name = d.localized?.name ?? d.global?.name;
				if (name && !cancelled) landedNames = { ...landedNames, [id]: name };
			})
			.catch((e) => console.warn(`[travel] could not name landed probe ${id}:`, e));
		return () => {
			cancelled = true;
		};
	}
	$effect(() => loadLandedName(fromId, fromLanded));
	$effect(() => loadLandedName(toId, toLanded));

	/** A point carries no name of its own, so its collection is asked for one.
	 *  The trip flies either way — the coordinates are the whole end — so a
	 *  collection that will not load costs the label and nothing else. */
	let padsBySlug = $state<Record<string, LaunchPad[]>>({});
	function loadPads(place: NavPlace | null) {
		const slug = place?.siteSlug;
		if (!slug || padsBySlug[slug]) return;
		let cancelled = false;
		void fetchLaunchPads(slug).then((pads) => {
			if (!cancelled) padsBySlug = { ...padsBySlug, [slug]: pads };
		});
		return () => {
			cancelled = true;
		};
	}
	$effect(() => loadPads(fromPlace));
	$effect(() => loadPads(toPlace));

	function padsFor(place: NavPlace | null): LaunchPad[] {
		return (place?.siteSlug && padsBySlug[place.siteSlug]) || [];
	}
	let originPads = $derived(padsFor(fromPlace));
	let targetPads = $derived(padsFor(toPlace));
	let originPad = $derived(
		fromPlace ? padAt(originPads, fromPlace.latDeg, fromPlace.lonDeg, fromPlace.padCode) : null
	);
	let targetPad = $derived(
		toPlace ? padAt(targetPads, toPlace.latDeg, toPlace.lonDeg, toPlace.padCode) : null
	);

	/** Put one end somewhere else and leave the other exactly as it stands —
	 *  read back off the view, since an end is more than its body. */
	function moveNav(end: NavEnd | null, at: 'from' | 'to') {
		if (!appState) return;
		const other = navEndOf(appState.view, at === 'from' ? 'to' : 'from');
		appState.setNav(at === 'from' ? end : other, at === 'from' ? other : end);
	}

	/** The same end moved to another pad: same body, same collection, new point. */
	function padEnd(id: string | null, place: NavPlace | null, pad: LaunchPad): NavEnd | null {
		if (id === null) return null;
		return {
			id,
			featureId: null,
			place: {
				latDeg: pad.latDeg,
				lonDeg: pad.lonDeg,
				siteSlug: place?.siteSlug ?? null,
				padCode: pad.code
			}
		};
	}

	/** What the picker chose, as an end. */
	function pickedEnd(pick: TravelEndpointPick): NavEnd {
		return { id: pick.bodyId, featureId: pick.featureId, place: pick.place ?? null };
	}

	/** What an end is called: the probe, the named place or the pad when it is one
	 *  of those, else the body. */
	function endpointName(
		body: BodyData,
		id: string | null,
		featureId: number | null,
		place: NavPlace | null,
		pad: LaunchPad | null
	): string {
		if (id !== null && landedNames[id]) return landedNames[id];
		// The place is the subject; what it holds goes on the line under it.
		if (pad) return pad.siteName;
		if (place) return displayName(body);
		if (featureId === null) return displayName(body);
		return featureNames[`${body.id}:${featureId}`] ?? displayName(body);
	}

	// Only the atmosphere is read, and only to decide whether an arrival gets an
	// aerocapture discount and a departure a drag loss. A failed fetch prices the
	// end airless, so it is logged rather than surfaced.
	let originDetail = $state<GlobalObjectData | null>(null);
	let targetDetail = $state<GlobalObjectData | null>(null);

	/**
	 * Which end each bundle was fetched for, and the guard that drops a superseded
	 * fetch. Plain variables rather than state: they are read inside the effects
	 * below to decide whether there is anything to do, and a reactive read there
	 * would make each effect depend on its own writes.
	 */
	let loadedFor = {
		origin: undefined as string | null | undefined,
		target: undefined as string | null | undefined
	};
	let detailToken = { origin: 0, target: 0 };

	/**
	 * Fetch the detail bundle for one end, unless that end is already the one it
	 * was fetched for.
	 *
	 * The early return is what keeps a re-run from clearing a good bundle: anything
	 * rendered on the strength of having one would flicker out and back, and a
	 * control that disappears between a press and its release swallows the click
	 * that was on it.
	 *
	 * Superseded fetches are dropped by token rather than cancelled on teardown,
	 * so a re-run for an unrelated reason cannot abandon a load in flight.
	 */
	function loadDetail(
		end: 'origin' | 'target',
		id: string | null,
		set: (d: GlobalObjectData | null) => void
	): void {
		if (loadedFor[end] === id) return;
		loadedFor[end] = id;
		set(null);
		if (id === null) return;

		const token = ++detailToken[end];
		fetchObjectDetail(id, false)
			.then((d) => {
				if (token === detailToken[end]) set(d.global);
			})
			.catch((e) => {
				console.warn(`[travel] no detail bundle for ${id}, pricing it airless:`, e);
				if (token === detailToken[end]) set(null);
			});
	}

	$effect(() => loadDetail('origin', originId, (d) => (originDetail = d)));
	$effect(() => loadDetail('target', targetId, (d) => (targetDetail = d)));

	// The header carries the panel's step back, rather than the panel growing a
	// second one under it: reading a trajectory, the crumb returns to the list it
	// came from; choosing between them, it is the destination as before.
	//
	// Which step that is comes off the trip's own terms — a named trajectory is
	// one being read — so nothing has to be handed up out of the panel.
	let reading = $derived(trip.profile);
	let crumb = $derived<Crumb | null>(
		reading
			? { label: m.travel_all_trajectories(), target: { kind: 'trip' } }
			: target
				? {
						label: displayName(target),
						target: { kind: 'focus', id: target.id, name: displayName(target) }
					}
				: null
	);
	let title = $derived(reading ? routeLabel(reading) : m.travel_title());

	// Mobile snap points: chrome-only collapsed (measured, so it tracks the real
	// header), mid, full. Unlike the detail sheet this one opens at the top — a
	// trip is what the page is for — but it still has to be draggable down, or
	// the map it is planning a route across is unreachable.
	const MID_SNAP = 0.4;
	// Leaves the same sliver of map above the sheet as the detail drawer does.
	const TOP_GAP_PX = 16;

	let innerH = $state(typeof window === 'undefined' ? 800 : window.innerHeight);
	let headerEl = $state<HTMLDivElement | null>(null);
	// Close to the rendered size (icon-lg row + handle + paddings) so the collapsed
	// snap is sane before the first measurement.
	const HEADER_GUESS_PX = 68;
	let headerHeightPx = $state(HEADER_GUESS_PX);
	let collapsedSnap = $derived(`${headerHeightPx}px`);
	let topSnap = $derived(`${Math.max(1, innerH - TOP_GAP_PX)}px`);
	let snapPoints = $derived([collapsedSnap, MID_SNAP, topSnap]);
	let activeSnapPoint = $state<number | string | null>(`${HEADER_GUESS_PX}px`);
	let isAtTop = $derived(activeSnapPoint === topSnap);

	// Opening the trip opens the sheet all the way. It has to be moved there after
	// mount rather than started there: vaul opens at its *first* snap point
	// whatever the bound value says, so a sheet handed the top snap up front just
	// sits collapsed. Moving it is also what animates it up.
	onMount(() => {
		const frame = requestAnimationFrame(() => (activeSnapPoint = topSnap));
		return () => cancelAnimationFrame(frame);
	});

	$effect(() => {
		let prev = window.innerHeight;
		const update = () => {
			const next = window.innerHeight;
			// Re-pin a top-snapped sheet to the new height. Otherwise a viewport resize
			// (the mobile keyboard) leaves activeSnapPoint on a px string that is no
			// longer in snapPoints, and vaul silently refuses to re-snap.
			if (activeSnapPoint === `${Math.max(1, prev - TOP_GAP_PX)}px`) {
				activeSnapPoint = `${Math.max(1, next - TOP_GAP_PX)}px`;
			}
			prev = next;
			innerH = next;
		};
		window.addEventListener('resize', update);
		return () => window.removeEventListener('resize', update);
	});

	$effect(() => {
		const el = headerEl;
		if (!el) return;
		const measure = () => {
			const h = Math.ceil(el.getBoundingClientRect().height);
			if (h === headerHeightPx) return;
			// Follow the new height when parked on the collapsed snap, so vaul is not
			// left on a snap point that no longer exists.
			const wasCollapsed = activeSnapPoint === collapsedSnap;
			headerHeightPx = h;
			if (wasCollapsed) activeSnapPoint = `${h}px`;
		};
		measure();
		const ro = new ResizeObserver(measure);
		ro.observe(el);
		return () => ro.disconnect();
	});

	// Report the snap target rather than sampling during the drag: a per-frame
	// getBoundingClientRect loop thrashes layout and makes the transition jank.
	$effect(() => {
		if (!isMobile) return;
		const s = activeSnapPoint;
		let dvh = 0;
		if (typeof s === 'number') {
			dvh = s * 100;
		} else if (typeof s === 'string') {
			const px = parseFloat(s);
			if (!Number.isNaN(px)) dvh = (px / window.innerHeight) * 100;
		}
		onSheetResize?.(dvh);
	});

	// Hand the viewport back on the way out, however the trip was left — otherwise
	// the map's controls stay parked above a sheet that is no longer there.
	$effect(() => () => onSheetResize?.(0));

	async function handleShare() {
		try {
			await navigator.clipboard.writeText(window.location.href);
			toast.success(m.link_copied());
		} catch (e) {
			console.warn('[travel] clipboard write refused:', e);
		}
	}
</script>

{#snippet toolbar()}
	<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={handleShare}>
		<Share2Icon />
		<span class="sr-only">{m.share()}</span>
	</Button>
	<Button variant="secondary" size="icon-lg" class="rounded-full" onclick={onClose}>
		<XIcon />
		<span class="sr-only">{m.close()}</span>
	</Button>
{/snippet}

{#snippet body(contentClass: string)}
	<div class={contentClass}>
		{#if origin || fromId === null || resolvedOnce}
			<TravelPanel
				{origin}
				{target}
				originName={fromId === null
					? null
					: origin
						? endpointName(origin, fromId, fromFeatureId, fromPlace, originPad)
						: (originDetail?.name ?? fromId)}
				targetName={toId === null
					? null
					: target
						? endpointName(target, toId, toFeatureId, toPlace, targetPad)
						: // Named but unplaceable: the bundle still knows what it is called, and
							// a destination that reads as empty would look like nothing was chosen.
							(targetDetail?.name ?? toId)}
				{originSite}
				{targetSite}
				{originPads}
				{targetPads}
				originPadCode={originPad?.code ?? null}
				targetPadCode={targetPad?.code ?? null}
				onOriginPadPick={(pad: LaunchPad) => moveNav(padEnd(fromId, fromPlace, pad), 'from')}
				onTargetPadPick={(pad: LaunchPad) => moveNav(padEnd(toId, toPlace, pad), 'to')}
				{refineBody}
				originPicked={fromId !== null}
				targetPicked={toId !== null}
				{nowJd}
				{excludeForOrigin}
				{excludeForTarget}
				bodiesById={tripBodies}
				{originDetail}
				{targetDetail}
				{trip}
				{viewFrame}
				{onPathChange}
				{onOptionsChange}
				{onHoverChange}
				{onTimelineChange}
				{onHazardsChange}
				resolveBodyName={(id) => names[id] ?? ctx?.getBody(id)?.data.name ?? id}
				onTripChange={(next) => appState?.setTrip(next)}
				onOriginChange={(pick: TravelEndpointPick) => moveNav(pickedEnd(pick), 'from')}
				onTargetChange={(pick: TravelEndpointPick) => moveNav(pickedEnd(pick), 'to')}
				onSwap={() => {
					if (!appState) return;
					appState.setNav(navEndOf(appState.view, 'to'), navEndOf(appState.view, 'from'));
				}}
			/>
		{:else if resolving}
			<p class="text-muted-foreground text-xs">{m.travel_locating_ends()}</p>
		{:else}
			<p class="text-muted-foreground text-xs">{m.travel_unknown_orbit()}</p>
		{/if}
	</div>
{/snippet}

{#if isMobile}
	<Vaul.Root
		open={true}
		{snapPoints}
		bind:activeSnapPoint
		shouldScaleBackground={false}
		dismissible={false}
		repositionInputs={false}
	>
		<Vaul.Portal>
			<Vaul.Content
				{inert}
				trapFocus={false}
				aria-labelledby="travel-drawer-title"
				class="bg-background fixed inset-x-0 bottom-0 z-50 flex h-dvh max-h-dvh flex-col rounded-t-xl border-t shadow-lg outline-none"
			>
				<div bind:this={headerEl} class="flex flex-col items-center gap-2 px-4 pt-3 pb-2">
					<div class="bg-muted-foreground/40 h-1 w-10 rounded-full"></div>
					<div class="flex w-full items-center justify-between gap-2">
						<DrawerTitle {crumb} {title} id="travel-drawer-title" />
						<div class="flex items-center gap-1.5">{@render toolbar()}</div>
					</div>
				</div>
				<div
					class="min-h-0 flex-1 {isAtTop ? 'overflow-y-auto' : 'overflow-hidden'}"
					style="padding-bottom: calc(1rem + {TOP_GAP_PX}px + var(--safe-bottom));"
				>
					{@render body('px-4 pt-4')}
				</div>
			</Vaul.Content>
		</Vaul.Portal>
	</Vaul.Root>
{:else}
	<aside
		{inert}
		aria-labelledby="travel-drawer-title"
		class="bg-background fixed start-0 top-0 z-50 flex h-full w-[var(--detail-panel)] max-w-[90vw] flex-col border-e shadow-lg"
	>
		<!-- pt aligns the title row with the top-4 featured chips beside it. -->
		<div class="flex items-center justify-between gap-2 px-4 pt-[18px] pb-2">
			<DrawerTitle {crumb} {title} id="travel-drawer-title" />
			<div class="flex items-center gap-1.5">{@render toolbar()}</div>
		</div>
		<ScrollArea class="min-h-0 flex-1">
			{@render body('px-4 pt-4 pb-4')}
		</ScrollArea>
	</aside>
{/if}
