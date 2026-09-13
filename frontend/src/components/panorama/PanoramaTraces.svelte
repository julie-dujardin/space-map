<!--
  The way into the panoramas from the 3D map, after Street View: every rover
  traverse on the focused body drawn on its ground as a thick blue line, with
  the nearest panorama shown as a card when the pointer rests on the line and
  opened by a click on it. A button in the corner stack takes the lines off
  the map. Standing on the body counts as focusing it — a landed rover, a
  crater — so the way in stays open from the ground; an orbiter's body is
  not the one it flies over. Bodies with no panoramas get neither.
-->
<script lang="ts">
	import { getContext } from 'svelte';
	import PersonStandingIcon from '@lucide/svelte/icons/person-standing';
	import * as m from '$lib/paraglide/messages.js';
	import { fetchObjectDetail, type PanoramaEntry } from '$lib/fetch/objects/object-data';
	import { versionedUrl } from '$lib/fetch/data-base';
	import { formatIsoDate } from '$lib/format/date';
	import { capitalize } from '$lib/search/format';
	import type { SpaceMap } from '$lib/scene/space-map.svelte';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import { TraverseTrace } from '$lib/panorama/trace';
	import { panoramaHref } from '$lib/panorama/traverse';

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
	let shown = $state(true);

	$effect(() => {
		const id = bodyId;
		let cancelled = false;
		entries = [];
		if (!id) return;
		fetchObjectDetail(id, false).then(
			(detail) => {
				if (!cancelled) entries = detail.global?.panoramas ?? [];
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

	/** The card: the panorama's preview over its mission and sol, a link into
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
		return {
			element: a,
			show(body, entry) {
				a.href = panoramaHref(body, entry);
				img.src = versionedUrl(`/v1/panoramas/${entry.id}-preview.webp`, 'panoramas');
				caption.textContent = `${capitalize(entry.mission ?? '')} · ${
					entry.sol === undefined ? formatIsoDate(entry.time) : m.panorama_sol({ sol: entry.sol })
				}`;
			}
		};
	}

	$effect(() => {
		const body = bodyId;
		const renderer = map.renderer;
		const data = body ? ctx.getBody(body)?.data : undefined;
		if (!shown || !body || !renderer || !data || !entries.length) return;
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
			const container = target?.closest('.sm-map');
			canvas = container?.querySelector('canvas') ?? null;
			if (!canvas) return hide();
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

{#if entries.length}
	<button
		type="button"
		onclick={() => (shown = !shown)}
		aria-pressed={shown}
		class="pointer-events-auto flex size-10 cursor-pointer items-center justify-center rounded-full backdrop-blur-md transition-colors md:size-8 {shown
			? 'bg-white text-black hover:bg-white/80'
			: 'bg-black/40 text-white hover:bg-black/55'}"
		title={shown ? m.panorama_entry_hide() : m.panorama_entry_show()}
		aria-label={shown ? m.panorama_entry_hide() : m.panorama_entry_show()}
	>
		<PersonStandingIcon class="size-5 md:size-4" />
	</button>
{/if}

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
