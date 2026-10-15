<!--
  The way into the panoramas from the 3D map, after Street View: every rover
  traverse on the focused body drawn on its ground as a thick blue line, with
  the nearest panorama shown as a card when the pointer rests on the line and
  opened by a click on it. A layer setting and immersive view take the lines
  off the map.
  Standing on the body counts as focusing it — a landed rover, a
  crater — so the way in stays open from the ground; an orbiter's body is
  not the one it flies over. Bodies with no panoramas get neither.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import {
		fetchObjectDetail,
		isViewable,
		type PanoramaEntry
	} from '$lib/fetch/objects/object-data';
	import { panoramaPreviewUrl } from '$lib/fetch/panoramas';
	import { formatIsoDate } from '$lib/format/date';
	import { capitalize } from '$lib/search/format';
	import type { SpaceMap } from '$lib/scene/space-map.svelte';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import { TraverseTrace } from '$lib/panorama/trace';
	import { crewName } from '$lib/panorama/traverses';
	import { panoramaHref } from '$lib/state/panorama-link';
	import { getSettings } from '$lib/state/settings.svelte';

	interface Props {
		map: SpaceMap;
		/** What the camera orbits, or null when nothing. */
		focused: PositionedBody | null;
	}

	let { map, focused }: Props = $props();

	/** Whether the focused probe stands on its parent. Read off the renderer,
	 *  which only learns it once the probe's ephemeris has streamed in, so it
	 *  is polled rather than read once at focus. */
	let landed = $state(false);

	$effect(() => {
		const probe = focused?.data.orbitalSource === OrbitalSource.SPICE_PROBE ? focused : null;
		const renderer = map.renderer;
		landed = false;
		if (!probe || !renderer) return;
		const poll = () => (landed = renderer.isLanded(probe.data.id));
		poll();
		const timer = setInterval(poll, 250);
		return () => clearInterval(timer);
	});

	/** The body whose ground the focus is on: the focus itself, or its host
	 *  for a surface feature or a landed probe. */
	const bodyId = $derived.by(() => {
		if (!focused) return null;
		if (focused.featureAnchor) return focused.featureAnchor.hostId;
		if (landed) return focused.data.parentId;
		return focused.data.id;
	});

	const ctx = getContext<ContextManager>('ctx');

	const WIDTH_PX = 15;
	/** How far from the line the pointer still counts as on it. */
	const REACH_PX = WIDTH_PX / 2 + 4;
	/** Above the drawn ground by more than its vertices' rounding, so the card
	 *  stands on it rather than in it. */
	const LIFT_KM = 0.01;

	let entries = $state<PanoramaEntry[]>([]);
	const settings = getSettings();

	$effect(() => {
		const id = bodyId;
		let cancelled = false;
		entries = [];
		if (!id) return;
		fetchObjectDetail(id, false).then(
			(detail) => {
				// The line goes only through stops that the viewer can open.
				if (!cancelled) entries = (detail.global?.panoramas ?? []).filter(isViewable);
			},
			(error) => console.warn('Panorama traces:', error)
		);
		return () => {
			cancelled = true;
		};
	});

	const byMission = $derived.by(() => {
		const groups = new Map<string, PanoramaEntry[]>();
		for (const e of entries)
			groups.set(e.mission ?? '', [...(groups.get(e.mission ?? '') ?? []), e]);
		return [...groups.values()];
	});

	/** The card: the panorama's preview over its craft and sol, a link into
	 *  it, with a hit disc at the place itself so the click lands where the
	 *  pointer already is. */
	function buildPreview(): {
		element: HTMLAnchorElement;
		show: (body: string, entry: PanoramaEntry) => void;
	} {
		const a = document.createElement('a');
		a.className = 'panorama-trace-preview sm-drawing--interactive';
		const img = document.createElement('img');
		img.alt = '';
		const caption = document.createElement('span');
		a.append(img, caption);
		let shown = '';
		return {
			element: a,
			show(body, entry) {
				a.href = panoramaHref(body, entry);
				img.src = panoramaPreviewUrl(entry);
				const mission = entry.mission ?? '';
				const when =
					entry.sol === undefined ? formatIsoDate(entry.time) : m.panorama_sol({ sol: entry.sol });
				// The craft is named by its page, which may still be on its way.
				caption.textContent = when;
				shown = entry.id;
				void crewName(body, mission).then((name) => {
					if (shown === entry.id) caption.textContent = `${name ?? capitalize(mission)} · ${when}`;
				});
			}
		};
	}

	$effect(() => {
		const body = bodyId;
		const renderer = map.renderer;
		const data = body ? ctx.getBody(body)?.data : undefined;
		if (!settings.showPanoramaTraces || settings.viewMode === 'immersive') return;
		if (!body || !renderer || !data || !entries.length) return;
		const radiusKm = effectiveRadiusKm(data);

		/** Height of the drawn ground under a panorama, above the mean radius;
		 *  the rover's own elevation while the terrain loads. */
		const ground = (e: PanoramaEntry): number => {
			const radial = renderer.surfaceRadialKm(body, e.lat, e.lon);
			return (radial === null ? (e.elevation_m ?? 0) / 1000 : radial - radiusKm) + LIFT_KM;
		};

		const trace = new TraverseTrace({
			body,
			runs: byMission,
			ground,
			widthPx: WIDTH_PX,
			color: '#60a5fa'
		});
		renderer.extensions.add(trace);

		const preview = buildPreview();
		const marker = map.addMarker({
			anchor: { body, latitude: 0, longitude: 0 },
			element: preview.element,
			align: [0.5, 1],
			occlude: true
		});
		marker.setVisible(false);
		let hovered = -1;
		let canvas: HTMLCanvasElement | null = null;

		const hide = () => {
			if (hovered < 0) return;
			hovered = -1;
			marker.setVisible(false);
			if (canvas) canvas.style.cursor = '';
			renderer.invalidate();
		};
		const onPointer = (e: PointerEvent) => {
			const target = e.target as Element | null;
			// Resting on the card is staying with it.
			if (target?.closest('.panorama-trace-preview')) return;
			// Only through open ground: a label, halo or marker over the line takes
			// the pointer for itself, so the line must not answer from under it.
			if (!target?.matches('.sm-map__canvas')) return hide();
			canvas = target as HTMLCanvasElement;
			const rect = canvas.getBoundingClientRect();
			const i = trace.nearest(e.clientX - rect.left, e.clientY - rect.top, REACH_PX);
			if (i < 0) return hide();
			if (i === hovered) return;
			hovered = i;
			const entry = trace.entryAt(i);
			preview.show(body, entry);
			marker.setAnchor({
				body,
				latitude: entry.lat,
				longitude: entry.lon,
				altitudeKm: ground(entry)
			});
			marker.setVisible(true);
			canvas.style.cursor = 'pointer';
			renderer.invalidate();
		};
		window.addEventListener('pointermove', onPointer);
		window.addEventListener('pointerdown', onPointer);

		return () => {
			window.removeEventListener('pointermove', onPointer);
			window.removeEventListener('pointerdown', onPointer);
			hide();
			marker.remove();
			renderer.extensions.remove(trace);
		};
	});
</script>

<style>
	:global(.panorama-trace-preview) {
		position: relative;
		display: block;
		width: 160px;
		/* Room between the card and the place it stands over. */
		padding-bottom: 14px;
		text-decoration: none;
	}
	/* The hit disc, straddling the place itself. */
	:global(.panorama-trace-preview::after) {
		content: '';
		position: absolute;
		left: 50%;
		top: 100%;
		width: 24px;
		height: 24px;
		transform: translate(-50%, -50%);
	}
	:global(.panorama-trace-preview img) {
		display: block;
		width: 100%;
		border-radius: 6px 6px 0 0;
	}
	:global(.panorama-trace-preview span) {
		display: block;
		padding: 3px 8px 4px;
		border-radius: 0 0 6px 6px;
		background: #3b82f6;
		color: #fff;
		font:
			bold 12px/1.3 system-ui,
			sans-serif;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		box-shadow: 0 2px 8px #000a;
	}
</style>
