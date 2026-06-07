<script lang="ts">
	import { onMount, setContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Scene from './Scene.svelte';
	import { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { SimClock } from '$lib/scene/state/clock.svelte';
	import { dateToJD } from '$lib/format/date';
	import { ObjectType, type PositionedBody } from '$lib/types/objects';
	import { minCameraDistance } from '$lib/scene/visibility/camera-limits';
	import { DEFAULT_VIEW, UrlType } from '$lib/state/view';
	import { createAppState } from '$lib/state/app-state.svelte';
	import { fetchBodyNomenclature, type NomenclatureFeature } from '$lib/fetch/nomenclature/fetch';
	import type { Focusable } from '$lib/state/focusable';
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
	import { localizedName } from '$lib/search/client';
	import { urlTypeFromId } from '$lib/state/url';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';

	const ctx = new ContextManager();
	setContext('ctx', ctx);

	const appState = createAppState();
	setContext('appState', appState);

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
		// Pre-load the filter so the first earth-zone pass lands filtered —
		// no flash of full SATCAT before the reload kicks in.
		if (appState.view.type === UrlType.Group && appState.view.groupSlug) {
			await ctx.applyGroupFilter(appState.view.groupSlug);
		}
		await ctx.load(appState.view.date, initialId);
		if (!ctx.getBody(initialId)) {
			toast.warning(m.object_not_found({ id: initialId }));
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
			<div class="fixed top-4 start-4 z-10 w-[min(360px,calc(100vw-7rem))] pointer-events-auto">
				<SearchBar
					onSelect={(hit) => {
						const name = localizedName(hit, getLocale());
						if (hit.kind === 'feature') {
							const diameterM = (hit.diameter_km ?? 0) * 1000;
							appState.setFeature({
								bodyId: hit.body_id,
								featureId: hit.feature_id,
								featureName: name
							});
							scene?.focusOnFeature(hit.body_id, hit.center_lat, hit.center_lon, diameterM);
						} else {
							appState.setFocus({
								type: urlTypeFromId(hit.id),
								id: hit.id,
								name
							});
							scene?.focusOnBody(hit.id);
						}
					}}
				/>
			</div>
			<div class="fixed top-4 end-4 z-10 flex flex-col items-end gap-3 pointer-events-auto">
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
