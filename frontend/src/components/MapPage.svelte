<script lang="ts">
	import { onMount, setContext, untrack } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Scene from './Scene.svelte';
	import { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { SimClock } from '$lib/scene/state/clock.svelte';
	import { dateToJD, jdToDate } from '$lib/format/date';
	import { ObjectType, type PositionedBody } from '$lib/types/objects';
	import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
	import { DEFAULT_VIEW, UrlType } from '$lib/state/view';
	import { createAppState } from '$lib/state/app-state.svelte';
	import { fetchBodyNomenclature, type NomenclatureFeature } from '$lib/fetch/nomenclature/fetch';
	import type { Focusable, FocusObject } from '$lib/state/focusable';
	import DetailDrawer from './detail/DetailDrawer.svelte';
	import MyLocation from './MyLocation.svelte';
	import ClearPromoted from './ClearPromoted.svelte';
	import CompassNorthSelector from './CompassNorthSelector.svelte';
	import { getNorthChoices } from '$lib/scene/camera/north-reference';
	import AttributionBar from './attribution/AttributionBar.svelte';
	import TimeControls from './time/TimeControls.svelte';
	import MobileTimeControls from './time/MobileTimeControls.svelte';
	import SettingsButton from './settings/SettingsButton.svelte';
	import LayersButton from './layers/LayersButton.svelte';
	import SearchBar from './search/SearchBar.svelte';
	import FeaturedBar from './search/FeaturedBar.svelte';
	import { isSearchEnabled, localizedName } from '$lib/search/client';
	import { coverageWindowFor, snapJdIntoWindow } from '$lib/fetch/coverage';
	import { fetchGroupDetail } from '$lib/fetch/groups/details';
	import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
	import { MISSION_SLUG_PREFIX } from '$lib/fetch/groups/registry';
	import { urlTypeFromId } from '$lib/state/url';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';

	const ctx = new ContextManager();
	setContext('ctx', ctx);

	const searchEnabled = isSearchEnabled();

	const appState = createAppState();
	setContext('appState', appState);

	// Generic focus for the search bar, featured chips, and in-drawer links:
	// snap into coverage, stream the body if absent, then frame it.
	const focusObject: FocusObject = (id, name, opts) => {
		void (async () => {
			const type = urlTypeFromId(id);
			// Snap into the coverage window if `now` is outside it — midpoint, not
			// the boundary, which has no sample and reads as out-of-range.
			const cov = await coverageWindowFor(id);
			const snap = cov ? snapJdIntoWindow(clock.jd, cov) : null;
			if (snap !== null) {
				const bounded = cov?.startJd !== undefined && cov.endJd !== undefined;
				clock.setJD(bounded ? (cov!.startJd! + cov!.endJd!) / 2 : snap);
			}

			// Stream an out-of-view target in place (probe/sat) — no page reload.
			if (!ctx.getBody(id)) await ctx.ensureBody(id, jdToDate(clock.jd));

			appState.setFocus({ type, id, name });

			const body = ctx.getBody(id);
			if (!body) {
				console.warn(`[map] focusObject: ${id} not resolvable — nothing to focus.`);
				return;
			}
			if (opts?.moveCamera === false) {
				// Re-anchor focus only, no fly (comet fragments).
				scene?.focusOnBody(id);
			} else if (type === UrlType.Probe || type === UrlType.EarthSatellite) {
				// Dive close when a 3D model exists; else hold distance (bare marker).
				const detail = await fetchObjectDetail(id, false);
				const distance = detail.global?.model_name ? minCameraDistance(body) * 5 : 0.005;
				scene?.focusOnBody(id, distance, DEFAULT_VIEW.latitude, DEFAULT_VIEW.longitude);
			} else {
				scene?.focusOnBody(id, minCameraDistance(body) * 5);
			}
		})();
	};
	setContext('focusObject', focusObject);

	// Open a /g/<slug> group view, framing its camera anchor at the default angle.
	function openGroup(slug: string, name: string) {
		appState.setGroup(slug, name);
		// setGroup parked view.id/zoom on the group anchor; DEFAULT_VIEW lat/lon
		// lands at the default framing instead of the prior angle.
		scene?.focusOnBody(
			appState.view.id,
			appState.view.zoom,
			DEFAULT_VIEW.latitude,
			DEFAULT_VIEW.longitude
		);
	}

	const clock = new SimClock(dateToJD(appState.view.date));
	// `.raw` — see Scene.svelte's `focusedBody` for the rationale (avoids deep
	// proxying of position/satrec, which the renderer and SGP4 mutate).
	let selectedBody = $state.raw<PositionedBody | undefined>();
	// Camera-truth focus: stays set after the drawer closes, since the renderer
	// is still tracking that body. Drives compass-north choices, which would
	// otherwise drop to "Solar System only" the moment the drawer is dismissed.
	let cameraFocus = $state.raw<PositionedBody | undefined>();
	let scene = $state<Scene>();
	let drawerHeightDvh = $state(0);
	let searchExpanded = $state(false);
	let userPromotedCount = $state(0);
	let northRefId = $state<string | null>(null);

	// Resolved feature record for the currently URL-pinned featureId. Driven by
	// the effect below; cleared when the URL has no feature or the lookup fails.
	let activeFeature = $state.raw<NomenclatureFeature | null>(null);
	// Plain (non-reactive) flag — only the URL-load case snaps the camera so
	// the page opens already-framed; in-session picks (search, label clicks,
	// browser nav) fly. Not a `$state` so toggling it inside the effect
	// doesn't re-trigger.
	let firstFeatureResolve = appState.view.featureId !== null;

	const northChoices = $derived.by(() => {
		void ctx.bodies.orientationVersion; // re-run when system data lands orientation
		return getNorthChoices(cameraFocus, ctx);
	});

	// Group route wins over body focus — camera may be parked on the anchor body.
	const focusable = $derived.by((): Focusable | null => {
		if (appState.view.type === UrlType.Group && appState.view.groupSlug) {
			return { kind: 'group', slug: appState.view.groupSlug };
		}
		if (!selectedBody?.data.id) return null;
		if (activeFeature) return { kind: 'feature', body: selectedBody, feature: activeFeature };
		return { kind: 'body', body: selectedBody };
	});

	// Desktop inset: park chips just past the 380px detail sidebar when open,
	// else the collapsed 240px search bar. Mobile stacks them below instead.
	const featuredStart = $derived(focusable ? 'calc(380px + 1rem)' : 'calc(240px + 2rem)');

	$effect(() => {
		if (northRefId === null) return;
		if (!northChoices.some((c) => c.id === northRefId)) northRefId = null;
	});

	// Repopulate selectedBody from ctx when a pinned featureId outlives a
	// drawer close — same-body picks emit no onFocusChange to do it for us.
	$effect(() => {
		if (selectedBody) return;
		if (appState.view.featureId === null) return;
		const target = ctx.getBody(appState.view.id);
		if (target) selectedBody = target;
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
		// Same feature already resolved — skip the refetch.
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
					scene?.focusOnFeature(bodyId, found.lat, found.lon, found.diameterM, firstFeatureResolve);
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

	onMount(async () => {
		const initialId = appState.view.id;
		// Friendly label from the URL slug; captured before the Sun fallback
		// below overwrites appState.view.name.
		const initialName = appState.view.name ?? initialId;
		// URL camera framing — restored onto the real target once it loads, since
		// the renderer settles its initial focus (on the parent) while the
		// target's chunk is still streaming.
		const { latitude, longitude, zoom } = appState.view;
		// Pre-load the filter so the first earth-zone pass lands filtered —
		// no flash of full SATCAT before the reload kicks in.
		if (appState.view.type === UrlType.Group && appState.view.groupSlug) {
			await ctx.applyGroupFilter(appState.view.groupSlug);
		}
		await ctx.load(appState.view.date, initialId);
		if (ctx.getBody(initialId)) {
			// A late-arriving target lands with the camera parked on its parent
			// (the renderer's initial fallback). Snap straight onto the real target
			// with the URL's framing — no fly, so the deep link opens already on it.
			// Skip if it's already focused (placeholder/early load).
			if (cameraFocus?.data.id !== initialId) {
				scene?.snapToBody(initialId, latitude, longitude, zoom);
			}
		} else {
			// Persistent (no auto-dismiss): the scene-load main-thread churn can
			// starve a transient toast so its duration timer expires before it ever
			// paints. A stable id de-dupes if the load is retried.
			toast.warning(m.object_not_found({ name: initialName }), {
				id: 'object-not-found',
				duration: Number.POSITIVE_INFINITY
			});
			appState.setFocus({ type: DEFAULT_VIEW.type, id: DEFAULT_VIEW.id, name: DEFAULT_VIEW.name });
		}
	});

	$effect(() => {
		const slug =
			appState.view.type === UrlType.Group && appState.view.groupSlug
				? appState.view.groupSlug
				: null;
		void ctx.applyGroupFilter(slug);
	});

	// Opening a mission flies the camera to its primary probe (snapping the clock
	// into coverage), unless we're already focused on one of its craft — then the
	// mission page just opens over the current view (member "Mission" card path).
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
			if (fromId && memberIds.has(fromId)) return; // already on a craft — keep camera
			const window = await coverageWindowFor(primary.primary_id);
			const body = ctx.getBody(primary.primary_id);
			// EVENTS-DB primaries have no ephemeris (no coverage, never streamed in)
			// — nothing to fly to. The mission page still opens; camera stays put.
			if (!window && !body) return;
			if (window) {
				const snap = snapJdIntoWindow(clock.jd, window);
				if (snap !== null) clock.setJD(snap);
			}
			scene?.focusOnBody(primary.primary_id, body ? minCameraDistance(body) * 5 : undefined);
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

{#if ctx.loading}
	<div class="flex items-center justify-center h-screen bg-bg text-text">{m.loading_data()}</div>
{:else if ctx.error}
	<div class="flex items-center justify-center h-screen bg-bg text-text-error">
		{m.error_prefix({ error: ctx.error })}
	</div>
{:else}
	<Tooltip.Provider delayDuration={300}>
		<div class="relative w-full h-screen">
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
					appState.setFeature({
						bodyId,
						featureId: fid,
						featureName: f.name
					});
					// activeFeature is resolved by the $effect above; here we just kick
					// the camera so the click feels instant instead of waiting on a
					// cache hit + microtask round-trip.
					scene?.focusOnFeature(bodyId, lat, lon, d);
				}}
				onUserPromotedChange={(count) => (userPromotedCount = count)}
			/>
			<TimeControls {clock} />
			<div
				class="fixed top-4 start-4 end-4 pointer-events-auto md:end-auto md:w-[min(400px,calc(100vw-7rem))] {searchExpanded
					? 'z-[55]'
					: 'z-10'}"
			>
				<SearchBar
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
							scene?.focusOnFeature(hit.body_id, hit.center_lat, hit.center_lon, diameterM);
							return;
						}
						if (hit.kind === 'group') {
							openGroup(hit.slug, name);
							return;
						}
						focusObject(hit.id, name);
					}}
				/>
			</div>
			{#if searchEnabled && !searchExpanded}
				<!-- Chips beside whatever's shown (sidebar/search bar); mobile stacks below. -->
				<div
					class="pointer-events-auto fixed start-4 end-4 top-[3.75rem] z-10 md:end-4 md:top-4 md:flex md:h-10 md:items-center md:start-[var(--featured-start)]"
					style="--featured-start: {featuredStart}"
				>
					<FeaturedBar onObject={(id, name) => focusObject(id, name)} onGroup={openGroup} />
				</div>
			{/if}
			<div
				class="fixed end-4 z-10 flex flex-col items-end gap-3 pointer-events-auto {searchEnabled
					? 'top-[7.5rem] md:top-4'
					: 'top-4'}"
			>
				<SettingsButton />
				<LayersButton />
			</div>
			{#if focusable}
				<DetailDrawer
					{focusable}
					{clock}
					onClose={() => {
						// One teardown path — no second drawer left under a feature/group close.
						const anchorId = selectedBody?.data.id ?? appState.view.id;
						selectedBody = undefined;
						activeFeature = null;
						appState.closeDetail(anchorId);
						drawerHeightDvh = 0;
					}}
					onMaximize={() => {
						if (!selectedBody) return;
						scene?.focusOnBody(selectedBody.data.id, minCameraDistance(selectedBody) * 5);
					}}
					onMinimize={() => {
						if (!selectedBody) return;
						// Pulls the camera back without changing focus — focusOnBody on the
						// already-focused id just runs the fly-to-camera path. Planets and
						// dwarf planets nominally orbit their planetary barycenter, but
						// treat them as sun-orbiters here so the minimize framing is the
						// whole solar system instead of just the planet's own subsystem.
						const { parentId, objectType } = selectedBody.data;
						const isSunOrbiter =
							parentId === 'naif-0' ||
							parentId === 'naif-10' ||
							objectType === ObjectType.PLANET ||
							objectType === ObjectType.DWARF_PLANET;
						const distance = isSunOrbiter ? DEFAULT_VIEW.zoom : 0.005;
						scene?.focusOnBody(selectedBody.data.id, distance);
					}}
					onSheetResize={(h) => (drawerHeightDvh = h)}
				/>
			{/if}
			<div
				class="fixed end-4 z-10 flex flex-col-reverse items-end gap-3 transition-[opacity,bottom] duration-300 ease-in-out
					{drawerHeightDvh > 12 ? 'opacity-0 pointer-events-none' : 'opacity-100'}"
				style="bottom: calc({Math.min(drawerHeightDvh, 12)}dvh + 1.5rem);"
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
			<div
				class="fixed end-0 z-10 transition-opacity duration-300 ease-in-out
					{drawerHeightDvh > 12 ? 'opacity-0 pointer-events-none' : 'opacity-100'}"
				style="bottom: {Math.min(drawerHeightDvh, 12)}dvh;"
			>
				<AttributionBar />
			</div>
		</div>
	</Tooltip.Provider>
{/if}
