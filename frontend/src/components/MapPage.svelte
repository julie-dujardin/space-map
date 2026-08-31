<script lang="ts">
	import { onMount, setContext, tick, untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Scene from './Scene.svelte';
	import { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { SimClock } from '$lib/scene/state/clock.svelte';
	import { dateToJD, formatJulianDate, jdToDate } from '$lib/format/date';
	import { ObjectType, type PositionedBody } from '$lib/types/objects';
	import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
	import { dominantPlanetId } from '$lib/scene/state/bodies.svelte';
	import {
		DEFAULT_FRAMING_LAT,
		DEFAULT_FRAMING_LON,
		DEFAULT_VIEW,
		DEFAULT_VIEW_ELEVATION_DEG,
		SUN_VIEW_ZOOM,
		UrlType
	} from '$lib/state/view';
	import { EARTH_ID, SUN_ID } from '$lib/constants';
	import { createAppState } from '$lib/state/app-state.svelte';
	import { getSettings } from '$lib/state/settings.svelte';
	import { fetchBodyNomenclature, type NomenclatureFeature } from '$lib/fetch/nomenclature/fetch';
	import type { Focusable, FocusFeature, FocusObject } from '$lib/state/focusable';
	import type { LabelledPath, PathStep } from '$lib/travel/labelled-path';
	import { craftPositionAt } from '$lib/math/travel/path-sample';
	import { legLabel } from './detail/travel/leg-labels';
	import type { TrajectoryFrame } from '$lib/math/travel';
	import SegmentedPill from './map-pill/SegmentedPill.svelte';
	import { frameOptions } from './travel-frame/frame-options';
	import { ringBrightnessOptions } from './rings/brightness-options';
	import type { Hazard } from '$lib/travel/hazards';
	import type { TimelineEntry, TimelineFocus } from '$lib/travel/timeline';
	// Lazy-loaded on first focus so its charts (d3-scale/d3-shape/layercake) and
	// member lists split out of the initial map chunk.
	let DetailDrawer = $state<typeof import('./detail/DetailDrawer.svelte').default | null>(null);
	// Same treatment for the trip planner: its Lambert kernel and porkchop chart
	// only load on /nav.
	let TravelDrawer = $state<typeof import('./detail/travel/TravelDrawer.svelte').default | null>(
		null
	);
	// The trip's own bottom bar, loaded with it rather than with the map.
	let TripTimeline = $state<typeof import('./detail/travel/TripTimeline.svelte').default | null>(
		null
	);
	// The same strip, for a spacecraft's own record — kept off while the
	// Targets tab carries it; flip to bring the strip back.
	const SHOW_PROBE_TIMELINE = false;
	let ProbeTimeline = $state<typeof import('./detail/probes/ProbeTimeline.svelte').default | null>(
		null
	);
	// The chosen trajectory as the planner hands it out: its legs for the timeline,
	// and its geometry so the timeline can put the camera on the arc itself.
	let timelineEntries = $state.raw<TimelineEntry[] | null>(null);
	let travelPlan = $state.raw<LabelledPath | null>(null);
	// The mounted timeline, so a step dot on the map can press the card it
	// stands for — playback stop included.
	let tripTimeline = $state<{ pickId: (id: string) => void } | null>(null);

	/**
	 * Which frame the drawn trip's ends are measured from. The map owns it
	 * since it changes the picture, not the trip. Only offered where the two
	 * frames would actually differ: a trip that escapes or captures.
	 */
	let viewFrame = $state<TrajectoryFrame>('planetary');
	let framesDiffer = $derived(
		travelPlan?.path.endOrbits.some((end) => end.approach.length > 1) ?? false
	);
	// The trajectories still being chosen between, drawn behind whatever is chosen
	// and labelled at both ends so either one can be taken off the map.
	let travelOptions = $state.raw<readonly LabelledPath[]>([]);
	// What the chosen trajectory puts the craft through, to band its arc with.
	let travelHazards = $state.raw<readonly Hazard[]>([]);
	import MyLocation from './MyLocation.svelte';
	import ClearPromoted from './ClearPromoted.svelte';
	import CompassNorthSelector from './CompassNorthSelector.svelte';
	import { getNorthChoices } from '$lib/scene/camera/north-reference';
	import AttributionBar from './attribution/AttributionBar.svelte';
	import TimeControls from './time/TimeControls.svelte';
	import MobileTimeControls from './time/MobileTimeControls.svelte';
	import SettingsButton from './settings/SettingsButton.svelte';
	import LayersButton from './layers/LayersButton.svelte';
	import SearchIcon from '@lucide/svelte/icons/search';
	import SearchBar from './search/SearchBar.svelte';
	import FeaturedBar from './search/FeaturedBar.svelte';
	import { isSearchEnabled, localizedName } from '$lib/search/client';
	import { coverageWindowFor, snapJdIntoWindow } from '$lib/fetch/coverage';
	import { watchDataVersion } from '$lib/fetch/version-check';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import { isModelBearing } from '$lib/scene/objects/body/model';
	import { MISSION_SLUG_PREFIX } from '$lib/fetch/groups/registry';
	import { urlTypeFromId } from '$lib/state/url';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as m from '$lib/paraglide/messages.js';
	import { loadProgress } from '$lib/scene/state/load-progress.svelte';
	import { scheduleAtmosphereCalibration } from '$lib/scene/perf/atmosphere-calibration';
	import { calibrationUi } from '$lib/scene/perf/calibration-state.svelte';
	import LoadingBar from './LoadingBar.svelte';
	import { startPageReload } from '$lib/reload';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';

	const ctx = new ContextManager();
	setContext('ctx', ctx);

	let reloading = $state(false);
	const startReload = () => startPageReload(() => (reloading = true));

	const searchEnabled = isSearchEnabled();

	const appState = createAppState();
	setContext('appState', appState);
	const settings = getSettings();

	// Snap the clock into `id`'s coverage window if `now` is outside it: the
	// midpoint, not the boundary (no sample there). No-op when there's no window.
	async function snapClockIntoCoverage(id: string) {
		const cov = await coverageWindowFor(id);
		const snap = cov ? snapJdIntoWindow(clock.jd, cov) : null;
		if (snap === null) return;
		const bounded = cov!.startJd !== undefined && cov!.endJd !== undefined;
		clock.setJD(bounded ? (cov!.startJd! + cov!.endJd!) / 2 : snap);
	}

	/** A system barycenter has no radius of its own, and for every planet but
	 *  Pluto it sits inside the primary — framing on it would put the camera under
	 *  the cloud tops. Frame the primary instead, so a system page opens where its
	 *  planet's page does. */
	function framingBody(body: PositionedBody): PositionedBody {
		const planetId = dominantPlanetId(body.data.id);
		return (planetId ? ctx.getBody(planetId) : undefined) ?? body;
	}

	/** Camera distance that frames `body`, or its primary when it is a barycenter.
	 *  A barycenter whose primary has not streamed in yet would otherwise frame on
	 *  a zero radius, which is the inside-the-planet case again — hold at the
	 *  default distance until there is a body to measure. */
	function framingZoom(body: PositionedBody): number {
		const framed = framingBody(body);
		if (framed.data.radiusKm <= 0) return DEFAULT_VIEW.zoom;
		return minCameraDistance(framed) * 5;
	}

	// Default camera distance: dive close to model/cuboid bodies, hold back for
	// bare markers. Sync (isModelBearing, no fetch) so the camera moves at once.
	function framingDistanceFor(type: string, body: PositionedBody): number {
		if (type === UrlType.Probe || type === UrlType.EarthSatellite) {
			return isModelBearing(body) ? minCameraDistance(body) * 5 : 0.005;
		}
		return framingZoom(body);
	}

	// Generic focus for the search bar, featured chips, and in-drawer links:
	// snap into coverage, stream the body if absent, then frame it.
	const focusObject: FocusObject = (id, name, opts) => {
		void (async () => {
			const type = urlTypeFromId(id);
			await snapClockIntoCoverage(id);

			// Stream an out-of-view target in place (probe/sat); no page reload.
			if (!ctx.getBody(id)) await ctx.ensureBody(id, jdToDate(clock.jd));

			appState.setFocus({ type, id, name, tab: opts?.tab, featureType: opts?.featureType });

			const body = ctx.getBody(id);
			if (!body) {
				console.warn(`[map] focusObject: ${id} not resolvable — nothing to focus.`);
				return;
			}
			if (body.positionUnknown) {
				// No ephemeris — at this time, or ever: take the focus so the drawer
				// opens, and say why the camera did not move.
				const label = name || id;
				toast.warning(
					body.data.unplaceable
						? m.object_position_unknown({ name: label })
						: m.object_no_position({ name: label }),
					{ id: 'object-no-position', closeButton: true }
				);
				scene?.focusOnBody(id);
			} else if (opts?.moveCamera === false) {
				// Re-anchor focus only, no fly (comet fragments).
				scene?.focusOnBody(id);
			} else if (type === UrlType.Probe || type === UrlType.EarthSatellite) {
				const distance = framingDistanceFor(type, body);
				scene?.focusOnBody(id, distance, DEFAULT_FRAMING_LAT, DEFAULT_FRAMING_LON);
			} else {
				scene?.focusOnBody(id, framingDistanceFor(type, body));
			}
		})();
	};
	setContext('focusObject', focusObject);

	// Feature picks from a collection page cross bodies: stream the host in and
	// point selectedBody at it, then the resolve effect below fetches its
	// nomenclature and frames the feature.
	const focusFeature: FocusFeature = (bodyId, featureId, name) => {
		void (async () => {
			await snapClockIntoCoverage(bodyId);
			if (!ctx.getBody(bodyId)) await ctx.ensureBody(bodyId, jdToDate(clock.jd));
			const body = ctx.getBody(bodyId);
			if (!body) {
				console.warn(`[map] focusFeature: host ${bodyId} not resolvable — nothing to focus.`);
				return;
			}
			selectedBody = body;
			appState.setFeature({ bodyId, featureId, featureName: name });
		})();
	};
	setContext('focusFeature', focusFeature);

	// Open a /g/<slug> group view, framing its camera anchor at the default angle.
	function openGroup(slug: string, name: string) {
		appState.setGroup(slug, name);
		// setGroup parked view.id/zoom on the group anchor; the default framing
		// angle lands the camera there instead of the prior angle.
		scene?.focusOnBody(
			appState.view.id,
			appState.view.zoom,
			DEFAULT_FRAMING_LAT,
			DEFAULT_FRAMING_LON
		);
	}

	const clock = new SimClock(dateToJD(appState.view.date));
	// `.raw`: see Scene.svelte's `focusedBody` (avoids deep proxying of
	// position/satrec, which the renderer and SGP4 mutate).
	let selectedBody = $state.raw<PositionedBody | undefined>();
	/**
	 * Whether the ring-brightness pill is on screen: only on the ring
	 * catalogue tab, where the true optical depths (e.g. Jupiter, Uranus)
	 * show next to nothing. Both flags read outright so both stay tracked.
	 */
	let ringPillShown = $derived.by(() => {
		const rings = !!selectedBody && appState.view.tab === 'rings';
		const frames = framesDiffer;
		return rings && !frames;
	});
	// Leaving the tab takes the overexposed picture with it: it is not the
	// physical one, and nothing off this tab explains why the rings are lit.
	$effect(() => {
		if (!ringPillShown) settings.setOverexposeRings(false);
	});
	// Camera-truth focus: stays set after the drawer closes since the renderer
	// keeps tracking that body. Drives compass-north choices, which would
	// otherwise drop to "Solar System only" the moment the drawer closes.
	let cameraFocus = $state.raw<PositionedBody | undefined>();
	let scene = $state<Scene>();
	let drawerHeightDvh = $state(0);
	let searchExpanded = $state(false);
	let searchBar = $state<SearchBar>();
	// The search overlay is fullscreen-modal on mobile but a non-modal side panel
	// on desktop, so only mobile inerts the background behind it.
	let isMobileViewport = $state(false);
	$effect(() => {
		const mq = window.matchMedia('(max-width: 767px)');
		isMobileViewport = mq.matches;
		const onChange = (e: MediaQueryListEvent) => (isMobileViewport = e.matches);
		mq.addEventListener('change', onChange);
		return () => mq.removeEventListener('change', onChange);
	});
	const bgInert = $derived(searchExpanded && isMobileViewport);
	let userPromotedCount = $state(0);
	let northRefId = $state<string | null>(null);

	// Resolved feature record for the currently URL-pinned featureId. Driven by
	// the effect below; cleared when the URL has no feature or the lookup fails.
	let activeFeature = $state.raw<NomenclatureFeature | null>(null);
	// Plain (non-reactive) flag: only the URL-load case snaps the camera so
	// the page opens already-framed; in-session picks (search, label clicks,
	// browser nav) fly. Not `$state` so toggling it inside the effect doesn't
	// re-trigger it.
	let firstFeatureResolve = appState.view.featureId !== null;
	// URL camera for the feature snap, captured before boot-time camera syncs
	// overwrite appState.view, to restore a shared link's exact framing.
	const initialFeatureView =
		firstFeatureResolve && appState.view.framed
			? {
					latitude: appState.view.latitude,
					longitude: appState.view.longitude,
					zoom: appState.view.zoom
				}
			: null;
	// Feature whose camera a 3D label click already drove (a pan in place). The
	// resolve effect skips re-driving it so the pan isn't restarted a beat later.
	let panFeatureId: number | null = null;
	// Orientation version the active feature was framed against. A cross-body
	// pick frames before the host's PCK orientation lands, seating the feature
	// in an unrotated frame; bumps here re-frame it once the real pole arrives.
	let framedOrientationVersion = -1;

	const northChoices = $derived.by(() => {
		void ctx.bodies.orientationVersion; // re-run when system data lands orientation
		void activeFeature; // re-run when a surface feature is focused/cleared
		return getNorthChoices(cameraFocus, ctx);
	});

	// One derived per end, not one object: `view` ticks twice a second, and an
	// object derived from it would get a fresh identity each tick, waking every
	// consumer's effects. Primitives compare equal.
	// `isNav`, not the presence of both ends, decides which sidebar renders —
	// the destination is null on the empty form.
	const isNav = $derived(appState.view.type === UrlType.Nav);
	const navFrom = $derived(isNav ? appState.view.navFrom : null);
	const navTo = $derived(isNav ? appState.view.navTo : null);
	const navFromFeature = $derived(isNav ? appState.view.navFromFeature : null);
	const navToFeature = $derived(isNav ? appState.view.navToFeature : null);
	const navFromPlace = $derived(isNav ? appState.view.navFromPlace : null);
	const navToPlace = $derived(isNav ? appState.view.navToPlace : null);

	// Group route wins over body focus: the camera may be parked on the anchor
	// body. A trip owns the sidebar outright: the destination is focused, but
	// the panel beside it is about the journey, not the body.
	const focusable = $derived.by((): Focusable | null => {
		if (isNav) return null;
		if (appState.view.type === UrlType.Group && appState.view.groupSlug) {
			return { kind: 'group', slug: appState.view.groupSlug };
		}
		if (!selectedBody?.data.id) return null;
		if (activeFeature) return { kind: 'feature', body: selectedBody, feature: activeFeature };
		return { kind: 'body', body: selectedBody };
	});

	// Kick off the drawer chunk fetch the first time anything is focused.
	$effect(() => {
		if (focusable && !DetailDrawer) {
			import('./detail/DetailDrawer.svelte').then((mod) => (DetailDrawer = mod.default));
		}
	});

	/** The focused craft, when one is focused and the planner isn't up — the
	 *  strip is one slot, and a trip being planned owns it. */
	let focusedProbeId = $derived(
		!isNav && selectedBody?.data.id.startsWith('probe-') ? selectedBody.data.id : null
	);

	$effect(() => {
		if (isNav && !TravelDrawer) {
			import('./detail/travel/TravelDrawer.svelte').then((mod) => (TravelDrawer = mod.default));
		}
		if (isNav && !TripTimeline) {
			import('./detail/travel/TripTimeline.svelte').then((mod) => (TripTimeline = mod.default));
		}
		if (SHOW_PROBE_TIMELINE && focusedProbeId && !ProbeTimeline) {
			import('./detail/probes/ProbeTimeline.svelte').then((mod) => (ProbeTimeline = mod.default));
		}
	});

	// The planner hands out the plan, its options, and its hazards separately,
	// and choosing a trajectory changes all three, so the redraw waits for
	// them to settle rather than building the whole overlay three times.
	let travelDrawQueued = false;
	function drawTravel(): void {
		if (travelDrawQueued) return;
		travelDrawQueued = true;
		queueMicrotask(() => {
			travelDrawQueued = false;
			scene?.setTravelPath(travelPlan, travelOptions, travelHazards, travelSteps());
		});
	}

	/** The trip's instant steps, as the map draws them: dots on the arc that
	 *  press their own timeline card. The end orbits stay off it — they are
	 *  places the trip is bracketed by, not things that happen on it. */
	function travelSteps(): PathStep[] {
		if (!travelPlan) return [];
		return (timelineEntries ?? [])
			.filter((e) => !e.isPhase && e.kind !== 'start-orbit' && e.kind !== 'final-orbit')
			.map((e) => ({
				id: e.id,
				kind: e.kind,
				bodyId: e.bodyId,
				jd: e.startJd,
				name: legLabel(e.kind),
				when: formatJulianDate(e.startJd),
				onPick: () => pickStep(e)
			}));
	}

	/** What pressing a step dot does: the timeline's own pick when it is up,
	 *  otherwise the same seek by hand. */
	function pickStep(entry: TimelineEntry): void {
		if (tripTimeline) {
			tripTimeline.pickId(entry.id);
			return;
		}
		clock.setJD(entry.startJd);
		const path = travelPlan?.path;
		const craft = path ? craftPositionAt(path, entry.startJd) : null;
		if (craft) {
			focusTimeline({ kind: 'point', centerId: craft.centerId, r: craft.r, track: true });
		} else if (entry.bodyId) {
			focusTimeline({ kind: 'body', bodyId: entry.bodyId });
		}
	}

	/** Look at whatever part of the trip the timeline was asked about. Never an
	 *  approach fly: reading a trip is picking places on a map from the vantage
	 *  built to read it from, and a fly throws that vantage away, especially
	 *  under autoplay. A tracked point moves now; the rest swings over. */
	function focusTimeline(target: TimelineFocus): void {
		if (target.kind === 'body') focusCameraOn(target.bodyId);
		else if (target.track) scene?.trackPathPoint(target.centerId, target.r);
		else scene?.focusOnPathPoint(target.centerId, target.r);
	}

	// Look at a body without touching the URL. On /nav the trip owns the URL, so
	// the ordinary focus path would close the planner to look at one of its own
	// waypoints.
	function focusCameraOn(id: string): void {
		void (async () => {
			if (!ctx.getBody(id)) {
				await ctx
					.ensureBody(id, jdToDate(clock.jd))
					.catch((e) => console.warn(`[map] timeline stop ${id} could not be streamed in:`, e));
			}
			scene?.focusOnBody(id);
		})();
	}

	// A non-resident trip end (probe, small body) has no elements to transfer
	// from: stream it in like focusObject would, then frame the destination.
	// Covers swaps and origin changes, which bypass setFocus.
	$effect(() => {
		if (!isNav) return;
		const to = navTo;
		// The clock ticks twice a second; reading it tracked would re-run this on
		// every tick.
		const at = jdToDate(untrack(() => clock.jd));
		const ends = [navFrom, to].filter((id) => id !== null);
		// Neither end chosen: nothing to stream, nothing to re-frame.
		if (ends.length === 0) return;
		void (async () => {
			await Promise.all(
				ends.map((id) =>
					ctx.getBody(id)
						? Promise.resolve()
						: ctx
								.ensureBody(id, at)
								.catch((e) => console.warn(`[map] trip end ${id} could not be streamed in:`, e))
				)
			);
			// With nowhere to go yet, the departure is the subject.
			const framed = to ?? ends[0];
			if (untrack(() => cameraFocus?.data.id) === framed) return;
			// Pan, don't fly: retargeting a trip is picking a place on a map, not
			// visiting it. Omitting the zoom holds the camera where it is and
			// only swings the pivot onto the new end.
			scene?.focusOnBody(framed);
		})();
	});

	// Desktop inset: park chips just past the detail sidebar (and the search
	// button beside it) when open, else the collapsed 240px search bar. Mobile
	// stacks them below instead.
	const featuredStart = $derived(
		focusable || isNav ? 'calc(var(--detail-panel) + 3.5rem)' : 'calc(240px + 2rem)'
	);

	// The sidebar covers the search bar on desktop, so a button beside it stands
	// in for the collapsed pill: close the sidebar, open search in its place.
	const sidebarOpen = $derived(Boolean(focusable) || isNav);
	function openSearchBesideSidebar() {
		if (isNav) closeTravel(false);
		else closeDetail(false);
		searchBar?.open();
	}

	// `refocusMain` off when the caller takes focus itself; otherwise focus
	// silently falls to <body> once the drawer unmounts.
	function closeDetail(refocusMain = true) {
		// One teardown path: no second drawer left under a feature/group close.
		const anchorId = selectedBody?.data.id ?? appState.view.id;
		selectedBody = undefined;
		activeFeature = null;
		appState.closeDetail(anchorId);
		drawerHeightDvh = 0;
		if (refocusMain) tick().then(() => document.getElementById('main-content')?.focus());
	}

	function closeTravel(refocusMain = true) {
		// Closing a trip lands on whichever end is framed, or on the body the
		// camera was left with when neither end is chosen.
		const id = navTo ?? navFrom ?? appState.view.id;
		appState.setFocus({ type: urlTypeFromId(id), id, name: '' });
		if (refocusMain) tick().then(() => document.getElementById('main-content')?.focus());
	}

	$effect(() => {
		if (northRefId === null) return;
		if (!northChoices.some((c) => c.id === northRefId)) northRefId = null;
	});

	// Repopulate selectedBody from ctx when a pinned featureId outlives a
	// drawer close: same-body picks emit no onFocusChange to do it for us.
	$effect(() => {
		if (selectedBody) return;
		if (appState.view.featureId === null) return;
		const target = ctx.getBody(appState.view.id);
		if (target) selectedBody = target;
	});

	// Re-frame the active feature when its host's orientation lands after the
	// framing (streamed-in host: the seat was computed unrotated).
	$effect(() => {
		const version = ctx.bodies.orientationVersion;
		const f = activeFeature;
		const body = selectedBody;
		if (!f || !body || framedOrientationVersion < 0 || version === framedOrientationVersion) return;
		framedOrientationVersion = version;
		scene?.focusOnFeature(body.data.id, f.featureId, f.lat, f.lon, f.diameterM, f.name, 'frame');
	});

	// Resolve `view.featureId` → `activeFeature` whenever either the URL's
	// featureId or the currently-selected body changes. Stale URLs (feature id
	// not in the body's nomenclature, or body has no nomenclature) get cleaned
	// out and we log so the swallow doesn't go silent.
	$effect(() => {
		const fid = appState.view.featureId;
		const body = selectedBody;
		if (fid === null || !body) {
			activeFeature = null;
			scene?.setSelectedFeature(null);
			return;
		}
		// Same feature already resolved: skip the refetch.
		if (activeFeature?.featureId === fid) return;
		// Cross-body pick: URL already names the new body but the camera
		// hasn't landed yet, so selectedBody is stale. Bail and wait for the
		// onFocusChange that flips selectedBody; the effect re-fires and
		// resolves against the right nomenclature then.
		if (body.data.id !== appState.view.id) return;
		const bodyId = body.data.id;
		let cancelled = false;
		fetchBodyNomenclature(bodyId)
			.then((features) => {
				if (cancelled || appState.view.featureId !== fid) return;
				const found = features.find((f) => f.featureId === fid);
				if (found) {
					activeFeature = found;
					scene?.setSelectedFeature(fid);
					// A label click already panned the camera in place; re-driving here
					// would restart the animation a beat later and hitch. Only the
					// effect-only paths (deep-link, browser nav) drive from here.
					if (panFeatureId === fid) {
						panFeatureId = null;
					} else {
						framedOrientationVersion = ctx.bodies.orientationVersion;
						scene?.focusOnFeature(
							bodyId,
							found.featureId,
							found.lat,
							found.lon,
							found.diameterM,
							found.name,
							firstFeatureResolve ? 'snap' : 'frame',
							firstFeatureResolve ? initialFeatureView : null
						);
					}
					firstFeatureResolve = false;
				} else {
					console.warn(
						`[map] Feature ${fid} not found on ${bodyId}; clearing URL feature selection.`
					);
					appState.clearFeature(body.data.name ?? '');
				}
			})
			.catch((err) => {
				if (cancelled) return;
				console.warn(`[map] Failed to resolve feature ${fid} on ${bodyId}:`, err);
				appState.clearFeature(body.data.name ?? '');
			});
		return () => {
			cancelled = true;
		};
	});

	// Prompt a reload when data looks stale after a redeploy (rotated `?v=`
	// tokens): on a tab-refocus version change or repeated refresher failures.
	onMount(() => {
		const showStale = () =>
			toast.warning(m.new_data_available(), {
				id: 'data-stale',
				duration: Number.POSITIVE_INFINITY,
				action: { label: m.reload(), onClick: () => location.reload() }
			});
		ctx.onDataStale = showStale;
		return watchDataVersion(showStale);
	});

	onMount(() => {
		// Runs behind the loading screen, in parallel with the data loads: the
		// screen holds until both settle, so the bench gets an uncontended GPU.
		scheduleAtmosphereCalibration();
	});

	onMount(async () => {
		const initialId = appState.view.id;
		// Friendly label from the URL slug; captured before the Sun fallback
		// below overwrites appState.view.name.
		const initialName = appState.view.name || initialId;
		// URL camera framing, restored onto the real target once it loads: the
		// renderer settles its initial focus on the parent while the target's
		// chunk is still streaming.
		const { latitude, longitude, zoom } = appState.view;
		// Pre-load the filter so the first earth-zone pass lands filtered: no
		// flash of full SATCAT before the reload kicks in.
		if (appState.view.type === UrlType.Group && appState.view.groupSlug) {
			await ctx.applyGroupFilter(appState.view.groupSlug);
		}
		// Snap the clock into range first (same path search takes), else an
		// `?at=` outside coverage would fail to resolve.
		await snapClockIntoCoverage(initialId);
		const loadPromise = ctx.load(jdToDate(clock.jd), initialId);
		loadPromise.catch((e) => console.error('[map] scene load failed:', e));
		// Frame as soon as the target's placeholder lands (phase 1, ~2s before
		// ctx.load resolves); fall through to the full load if it never shows.
		await Promise.race([
			loadPromise.catch(() => {}),
			new Promise<void>((resolve) => {
				const check = () => {
					if (scene && ctx.getBody(initialId)) resolve();
					// Timer alongside the frame: a backgrounded tab fires no rAF, and
					// the poll would never come back.
					else if (document.hidden) setTimeout(check, 100);
					else requestAnimationFrame(check);
				};
				check();
			})
		]);
		// Error screen already shown: don't also fire the "not found" toast over it.
		if (ctx.error) return;
		if (!ctx.getBody(initialId)) {
			// The load pass can't graft a probe whose only record needs its
			// stamped fit-center streamed first (Deep Impact → Tempel 1);
			// ensureBody owns that chain, so give it one shot before landing
			// on the not-found fallback.
			await ctx
				.ensureBody(initialId, jdToDate(clock.jd))
				.catch((e) => console.warn(`[map] initial target ${initialId} could not be streamed:`, e));
		}
		let initialBody = ctx.getBody(initialId);
		// A freshly grafted probe can spend a few frames unplaced while its
		// stamped fit center streams in and the position pass picks it up —
		// don't judge it unplaceable until that settles.
		if (initialBody?.positionUnknown) {
			const deadline = performance.now() + 1500;
			while (initialBody?.positionUnknown && performance.now() < deadline) {
				// Timer alongside the frame: a backgrounded tab fires no rAF, and the
				// wait would never end for a body that is never placed.
				await Promise.race([
					new Promise(requestAnimationFrame),
					new Promise((resolve) => setTimeout(resolve, 100))
				]);
				initialBody = ctx.getBody(initialId);
			}
		}
		// A body that is resident but has no ephemeris at this time carries a
		// stand-in position (its parent, or the scene origin), so there is
		// nothing to fly to — it keeps the focus, the camera stays put.
		const placed = initialBody?.positionUnknown ? undefined : initialBody;
		if (placed && appState.view.featureId !== null) {
			// Feature deep-link: the featureId→activeFeature effect frames the
			// camera on the feature seat. Skip host framing here, it runs after
			// that effect and would clobber the feature focus.
		} else if (placed) {
			if (initialId === EARTH_ID && !appState.view.framed) {
				// Home view (`/` redirects here): Earth looking sunward, tilted above the ecliptic.
				scene?.snapToBodyFacing(initialId, SUN_ID, DEFAULT_VIEW_ELEVATION_DEG, DEFAULT_VIEW.zoom);
			} else if (!appState.view.framed) {
				// No URL camera: frame by the target's size/model, same as search.
				const distance = framingDistanceFor(appState.view.type, placed);
				scene?.snapToBody(initialId, DEFAULT_FRAMING_LAT, DEFAULT_FRAMING_LON, distance);
			} else if (cameraFocus?.data.id !== initialId) {
				// Explicit URL camera, but the renderer settled on the parent while
				// the target streamed: snap onto it (no fly, opens already framed).
				scene?.snapToBody(initialId, latitude, longitude, zoom);
			}
		} else if (isNav) {
			// A trip end the scene cannot place is the panel's story to tell.
			// Falling back to the default view would drop the whole trip out of
			// the URL, so only the camera moves, onto the other end, which is
			// what the empty form frames anyway.
			const fromId = navFrom;
			const departure = fromId === null ? null : ctx.getBody(fromId);
			if (fromId && departure) {
				scene?.snapToBody(
					fromId,
					DEFAULT_FRAMING_LAT,
					DEFAULT_FRAMING_LON,
					framingDistanceFor(urlTypeFromId(fromId), departure)
				);
			}
		} else if (initialBody) {
			// Unplaceable, but its drawer still has everything to show: hold the
			// focus the URL asked for and say why the camera did not move.
			toast.warning(
				initialBody.data.unplaceable
					? m.object_position_unknown({ name: initialName })
					: m.object_no_position({ name: initialName }),
				{
					id: 'object-no-position',
					duration: Number.POSITIVE_INFINITY,
					closeButton: true
				}
			);
			// The renderer settles its own focus on a placed body and refuses an
			// unplaced one, so this call is the only thing that opens the drawer
			// here — retry until it takes, since the scene can still be mounting
			// when the load pass wins the race above.
			const focusBy = performance.now() + 3000;
			do {
				scene?.focusOnBody(initialId);
				if (cameraFocus?.data.id === initialId) break;
				await new Promise((resolve) => setTimeout(resolve, 50));
			} while (performance.now() < focusBy);
		} else {
			// Persistent (no auto-dismiss): the scene-load main-thread churn can
			// starve a transient toast so its duration timer expires before it ever
			// paints. A stable id de-dupes if the load is retried.
			toast.warning(m.object_not_found({ name: initialName }), {
				id: 'object-not-found',
				duration: Number.POSITIVE_INFINITY,
				closeButton: true
			});
			appState.setFocus({ type: DEFAULT_VIEW.type, id: DEFAULT_VIEW.id, name: DEFAULT_VIEW.name });
			// The renderer settled the camera on whatever it could find (the Sun);
			// land on the default view instead, so an unknown URL opens home.
			scene?.snapToBodyFacing(
				DEFAULT_VIEW.id,
				SUN_ID,
				DEFAULT_VIEW_ELEVATION_DEG,
				DEFAULT_VIEW.zoom
			);
		}
	});

	$effect(() => {
		const slug =
			appState.view.type === UrlType.Group && appState.view.groupSlug
				? appState.view.groupSlug
				: null;
		void ctx.applyGroupFilter(slug);
	});

	// Opening a mission flies the camera to its primary probe (snapping the
	// clock into coverage), unless already focused on one of its craft, in
	// which case the mission page just opens over the current view.
	let missionFlownSlug: string | null = null;
	$effect(() => {
		// Read scene/loading synchronously so a direct /g/mission-… load retries
		// once the renderer mounts (the effect first runs while ctx.loading).
		const ready = !ctx.loading && scene;
		const slug =
			appState.view.type === UrlType.Group && appState.view.groupSlug
				? appState.view.groupSlug
				: null;
		if (!slug?.startsWith(MISSION_SLUG_PREFIX)) {
			missionFlownSlug = null;
			return;
		}
		if (!ready || slug === missionFlownSlug) return;
		missionFlownSlug = slug;
		const fromId = untrack(() => cameraFocus?.data.id);
		void (async () => {
			const detail = await fetchGroupDetail(slug);
			if (appState.view.groupSlug !== slug) return;
			const primary = detail.global?.primary;
			if (!primary) return;
			const memberIds = new Set(
				(detail.global?.notable_members ?? []).map((mm) => mm.id).filter(Boolean)
			);
			if (fromId && memberIds.has(fromId)) return; // already on a craft, keep camera
			const window = await coverageWindowFor(primary.primary_id);
			const body = ctx.getBody(primary.primary_id);
			// EVENTS-DB primaries have no ephemeris: nothing to fly to. The
			// mission page still opens; camera stays put.
			if (!window && !body) return;
			if (window) {
				const snap = snapJdIntoWindow(clock.jd, window);
				if (snap !== null) clock.setJD(snap);
			}
			scene?.focusOnBody(primary.primary_id, body ? framingZoom(body) : undefined);
		})();
	});
</script>

<svelte:head>
	<title
		>{selectedBody && appState.view.name
			? `${appState.view.name} - ${m.page_title()}`
			: m.page_title()}</title
	>
</svelte:head>

{#if ctx.loading || calibrationUi.bootPending}
	<div
		class="flex h-screen flex-col items-center justify-center gap-3 bg-bg text-text"
		role="status"
		aria-live="polite"
	>
		{#if ctx.loading}
			<span class="text-sm">{m.loading_data()}</span>
			<LoadingBar value={loadProgress.value} label={m.loading_data()} />
		{:else}
			<span class="text-sm">{m.settings_recalibrate_running()}</span>
			<LoadingBar
				value={calibrationUi.progress ?? undefined}
				label={m.settings_recalibrate_running()}
			/>
		{/if}
	</div>
{:else if ctx.error}
	<div
		role="alert"
		class="flex h-screen flex-col items-center justify-center gap-4 bg-bg px-6 text-center"
	>
		<p class="max-w-md text-sm text-text-error">{m.error_prefix({ error: ctx.error })}</p>
		<button
			class="rounded-md bg-text px-4 py-2 text-sm font-medium text-bg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:opacity-50"
			disabled={reloading}
			onclick={startReload}
		>
			{m.reload()}
		</button>
		{#if reloading}
			<LoadingBar label={m.reload()} />
		{/if}
	</div>
{:else}
	<Tooltip.Provider delayDuration={300}>
		<a
			href="#main-content"
			inert={bgInert}
			class="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:start-2 focus:z-[100] focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:text-foreground focus:shadow-lg focus:outline-none focus:ring-2 focus:ring-ring"
		>
			{m.skip_to_content()}
		</a>
		<main id="main-content" tabindex="-1" class="relative w-full h-screen outline-none">
			<!-- Visually-hidden h1 so screen readers get a stable page-title
			     landmark even when the drawer is closed. -->
			<h1 class="sr-only">{appState.view.name || m.page_title()}</h1>
			<!-- display:contents wrapper so mobile's fullscreen search can inert the
			     scene without adding a layout box. -->
			<div class="contents" inert={bgInert}>
				<Scene
					bind:this={scene}
					{clock}
					{northRefId}
					onFocusChange={(body) => {
						cameraFocus = body;
						selectedBody = body;
					}}
					onFeatureSelect={async (bodyId, fid, lat, lon, d) => {
						const features = await fetchBodyNomenclature(bodyId);
						const f = features.find((x) => x.featureId === fid);
						if (!f) {
							console.warn(`[map] Clicked feature ${fid} on ${bodyId} not in fetched list.`);
							return;
						}
						// A visible label was clicked → pan in place, and tell the resolve
						// effect not to re-drive (which would restart the pan).
						panFeatureId = fid;
						appState.setFeature({
							bodyId,
							featureId: fid,
							featureName: f.name
						});
						// The $effect above resolves activeFeature; kick the camera here
						// so the click feels instant instead of waiting on it.
						scene?.focusOnFeature(bodyId, fid, lat, lon, d, f.name, 'pan');
					}}
					onUserPromotedChange={(count) => (userPromotedCount = count)}
				/>
			</div>
			<TimeControls {clock} />
			<div
				class="fixed top-[calc(var(--safe-top)_+_1rem)] start-[calc(var(--safe-start)_+_1rem)] end-[calc(var(--safe-end)_+_1rem)] pointer-events-auto md:end-auto md:w-[min(400px,calc(100vw-7rem))] {searchExpanded
					? 'z-[55]'
					: 'z-10'}"
			>
				<SearchBar
					bind:this={searchBar}
					onExpandedChange={(v) => (searchExpanded = v)}
					onSelect={async (hit) => {
						const name = localizedName(hit, getLocale());
						if (hit.kind === 'feature') {
							const diameterM = (hit.diameter_km ?? 0) * 1000;
							appState.setFeature({
								bodyId: hit.body_id,
								featureId: hit.feature_id,
								featureName: name
							});
							scene?.focusOnFeature(
								hit.body_id,
								hit.feature_id,
								hit.center_lat,
								hit.center_lon,
								diameterM,
								name,
								'frame'
							);
							return;
						}
						if (hit.kind === 'group') {
							openGroup(hit.slug, name);
							return;
						}
						// A pad has no page of its own — the range holding it is what
						// there is to read, and the planner is where a pad is a place.
						if (hit.kind === 'pad') {
							openGroup(hit.site_slug, hit.site_name);
							return;
						}
						focusObject(hit.id, name);
					}}
				/>
			</div>
			{#if searchEnabled && !searchExpanded && sidebarOpen}
				<!-- Desktop only: on mobile the sidebar is a sheet that leaves the
				     search bar in the clear. h-10 box with the chip strip's own bottom
				     padding, so the circle lands on the chips' centre line. -->
				<button
					type="button"
					class="pointer-events-auto fixed top-[calc(var(--safe-top)_+_1rem)] z-10 hidden h-10 items-center pb-1 md:flex md:start-[calc(var(--detail-panel)_+_1rem)]"
					title={m.search_placeholder()}
					aria-label={m.search_placeholder()}
					onclick={openSearchBesideSidebar}
				>
					<span
						class="flex h-8 w-8 items-center justify-center rounded-full border border-border bg-popover/90 text-muted-foreground shadow-lg backdrop-blur-md transition-colors hover:bg-accent hover:text-foreground"
					>
						<SearchIcon class="size-4" />
					</span>
				</button>
			{/if}
			{#if searchEnabled && !searchExpanded}
				<!-- Chips beside whatever's shown (sidebar/search bar); mobile stacks below.
				     A phone has one row there, so the map pill takes it when it appears:
				     shortcuts away from the map matter less than the control for what the
				     reader is looking at. -->
				<div
					class="pointer-events-auto fixed start-[calc(var(--safe-start)_+_1rem)] end-[calc(var(--safe-end)_+_1rem)] top-[calc(var(--safe-top)_+_4.125rem)] z-10 md:end-[calc(var(--safe-end)_+_1rem)] md:top-[calc(var(--safe-top)_+_1rem)] md:flex md:h-10 md:items-center md:start-[var(--featured-start)]
						{framesDiffer || ringPillShown ? 'max-md:hidden' : ''}"
					style="--featured-start: {featuredStart}"
				>
					<FeaturedBar
						onObject={(id, name) => focusObject(id, name)}
						onGroup={openGroup}
						onFeature={focusFeature}
					/>
				</div>
			{/if}
			<div
				inert={bgInert}
				class="fixed end-[calc(var(--safe-end)_+_1rem)] z-10 flex flex-col items-end gap-3 pointer-events-auto {searchEnabled
					? 'top-[calc(var(--safe-top)_+_7.5rem)] md:top-[calc(var(--safe-top)_+_1rem)]'
					: 'top-[calc(var(--safe-top)_+_1rem)]'}"
			>
				<SettingsButton />
				<LayersButton />
			</div>
			{#if isNav && TravelDrawer}
				<TravelDrawer
					fromId={navFrom}
					toId={navTo}
					fromFeatureId={navFromFeature}
					toFeatureId={navToFeature}
					fromPlace={navFromPlace}
					toPlace={navToPlace}
					clockJd={clock.jd}
					clockSettledJd={clock.settledJd}
					isMobile={isMobileViewport}
					{viewFrame}
					inert={bgInert}
					onPathChange={(plan) => {
						travelPlan = plan;
						drawTravel();
					}}
					onOptionsChange={(options) => {
						travelOptions = options;
						drawTravel();
					}}
					onHoverChange={(id) => scene?.setTravelHover(id)}
					onTimelineChange={(entries) => {
						timelineEntries = entries;
						drawTravel();
					}}
					onHazardsChange={(hazards) => {
						travelHazards = hazards;
						drawTravel();
					}}
					onOrbitPreview={(previews, frame) => scene?.setOrbitPreview(previews, frame)}
					onClose={() => closeTravel()}
					onSheetResize={(h) => (drawerHeightDvh = h)}
				/>
			{/if}
			{#if SHOW_PROBE_TIMELINE && focusedProbeId && ProbeTimeline}
				<div inert={bgInert} class="contents">
					<ProbeTimeline
						objectId={focusedProbeId}
						name={appState.view.name || focusedProbeId}
						{clock}
					/>
				</div>
			{/if}
			{#if isNav && TripTimeline && timelineEntries && timelineEntries.length > 1}
				<div inert={bgInert} class="contents">
					<TripTimeline
						bind:this={tripTimeline}
						entries={timelineEntries}
						path={travelPlan?.path ?? null}
						{clock}
						onFocus={focusTimeline}
					/>
				</div>
			{/if}
			{#if focusable && DetailDrawer}
				<DetailDrawer
					{focusable}
					{clock}
					inert={bgInert}
					onClose={() => closeDetail()}
					onMaximize={() => {
						if (!selectedBody) return;
						scene?.focusOnBody(selectedBody.data.id, framingZoom(selectedBody));
					}}
					onMinimize={() => {
						if (!selectedBody) return;
						// Planets and dwarf planets nominally orbit their planetary
						// barycenter, but are treated as sun-orbiters here so the minimize
						// framing is the whole solar system, not just the subsystem.
						const { parentId, objectType } = selectedBody.data;
						const isSunOrbiter =
							parentId === 'naif-0' ||
							parentId === 'naif-10' ||
							objectType === ObjectType.PLANET ||
							objectType === ObjectType.DWARF_PLANET;
						const distance = isSunOrbiter ? SUN_VIEW_ZOOM : 0.005;
						scene?.focusOnBody(selectedBody.data.id, distance);
					}}
					onSheetResize={(h) => (drawerHeightDvh = h)}
				/>
			{/if}
			<div
				inert={bgInert}
				class="fixed end-[calc(var(--safe-end)_+_1rem)] z-10 flex flex-col-reverse items-end gap-3 transition-[opacity,bottom] duration-300 ease-in-out
					{drawerHeightDvh > 12 ? 'opacity-0 pointer-events-none' : 'opacity-100'}"
				style="bottom: calc({Math.min(drawerHeightDvh, 12)}dvh + 1.5rem + var(--safe-bottom));"
			>
				<div class="md:hidden pointer-events-auto">
					<MobileTimeControls {clock} />
				</div>
				<MyLocation
					onLocate={(zoom: number, lat?: number, lng?: number) => {
						if (lat !== undefined && lng !== undefined) scene?.setUserLocation(lat, lng);
						return scene?.focusOnBody('naif-399', zoom, lat, lng) ?? 0;
					}}
				/>
				{#if northChoices.length > 1}
					<CompassNorthSelector
						choices={northChoices}
						selectedId={northRefId}
						onSelect={(id) => (northRefId = id)}
					/>
				{/if}
				{#if userPromotedCount > 0}
					<ClearPromoted count={userPromotedCount} onClear={() => scene?.clearUserPromoted()} />
				{/if}
			</div>
			{#if framesDiffer || ringPillShown}
				<!-- Centred on the window, not the map area left beside the planner:
				     measured off that, it would slide sideways as the panel opens/closes. -->
				<div
					inert={bgInert}
					class="pointer-events-none fixed start-[var(--safe-start)] end-[var(--safe-end)] z-10 flex
						justify-center top-[calc(var(--safe-top)_+_4.125rem)] md:top-[calc(var(--safe-top)_+_4rem)]"
				>
					<!-- One slot, so the two never stack: the planner and a body's ring
					     catalogue are not open at the same time. -->
					{#if framesDiffer}
						<SegmentedPill
							label={m.travel_frame()}
							options={frameOptions()}
							value={viewFrame}
							onSelect={(next) => (viewFrame = next)}
						/>
					{:else}
						<SegmentedPill
							label={m.rings_brightness()}
							shortLabel={m.tab_rings()}
							options={ringBrightnessOptions()}
							value={settings.overexposeRings}
							onSelect={(next) => settings.setOverexposeRings(next)}
						/>
					{/if}
				</div>
			{/if}
			<div
				inert={bgInert}
				class="fixed end-[var(--safe-end)] z-10 transition-opacity duration-300 ease-in-out
					{drawerHeightDvh > 12 ? 'opacity-0 pointer-events-none' : 'opacity-100'}"
				style="bottom: calc({Math.min(drawerHeightDvh, 12)}dvh + var(--safe-bottom));"
			>
				<AttributionBar />
			</div>
		</main>
	</Tooltip.Provider>
{/if}
