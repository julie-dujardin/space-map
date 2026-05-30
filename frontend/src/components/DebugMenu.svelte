<script lang="ts">
	import { onMount } from 'svelte';
	import type { SceneRenderer } from '$lib/scene/renderer';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { getSettings } from '$lib/state/settings.svelte';
	import * as m from '$lib/paraglide/messages.js';

	interface Props {
		getRenderer: () => SceneRenderer | undefined;
		ctx: ContextManager;
		clock: SimClock;
	}

	let { getRenderer, ctx, clock }: Props = $props();
	const settings = getSettings();

	type Stats = ReturnType<SceneRenderer['getDebugStats']>;
	type Counts = ReturnType<ContextManager['bodies']['getObjectCounts']>;

	let stats = $state<Stats | null>(null);
	let counts = $state<Counts>({
		planets: 0,
		moons: 0,
		probes: 0,
		earthSatellites: 0,
		smallBodies: 0
	});
	// performance.memory is a non-standard Chromium-only field; surface it
	// when available, hide the row when not.
	let jsHeapMB = $state<number | null>(null);

	function fmtInt(n: number): string {
		return n.toLocaleString();
	}
	function fmtAU(d: number): string {
		if (d < 1e-4) return `${(d * 149_597_870.7).toFixed(0)} km`;
		if (d < 1) return `${d.toFixed(4)} AU`;
		return `${d.toFixed(2)} AU`;
	}

	onMount(() => {
		let raf = 0;
		// Poll once per ~250ms — enough to keep the panel responsive without
		// adding measurable work to the render loop.
		let lastPoll = 0;
		const tick = (now: number) => {
			raf = requestAnimationFrame(tick);
			if (now - lastPoll < 250) return;
			lastPoll = now;
			const r = getRenderer();
			if (!r) return;
			stats = r.getDebugStats();
			counts = ctx.bodies.getObjectCounts();
			// @ts-expect-error — non-standard Chromium API
			const mem = performance.memory;
			if (mem?.usedJSHeapSize != null) jsHeapMB = mem.usedJSHeapSize / 1_048_576;
		};
		raf = requestAnimationFrame(tick);
		return () => cancelAnimationFrame(raf);
	});

	let totalObjects = $derived(
		counts.planets + counts.moons + counts.probes + counts.earthSatellites + counts.smallBodies
	);
</script>

<div
	class="absolute top-3 start-3 z-10 pointer-events-auto
		rounded-md bg-background/80 backdrop-blur-sm border border-border/60
		px-3 py-2 text-[11px] font-mono leading-tight text-foreground/90
		shadow-md max-w-[260px] select-text"
	role="status"
	aria-live="off"
>
	<div class="font-semibold text-foreground mb-1">{m.debug_title()}</div>

	<div class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
		<span class="text-muted-foreground">{m.debug_fps()}</span>
		<span class="text-end tabular-nums">{stats ? stats.fps.toFixed(0) : '—'}</span>

		<span class="text-muted-foreground">{m.debug_workers()}</span>
		<span class="text-end tabular-nums">
			{#if stats}{stats.workers} · {stats.workerGroups} {m.debug_groups()}{:else}—{/if}
		</span>

		<span class="text-muted-foreground">{m.debug_draw_calls()}</span>
		<span class="text-end tabular-nums">{stats ? fmtInt(stats.drawCalls) : '—'}</span>

		<span class="text-muted-foreground">{m.debug_triangles()}</span>
		<span class="text-end tabular-nums">{stats ? fmtInt(stats.triangles) : '—'}</span>

		<span class="text-muted-foreground">{m.debug_geometries()}</span>
		<span class="text-end tabular-nums">{stats ? fmtInt(stats.geometries) : '—'}</span>

		<span class="text-muted-foreground">{m.debug_textures()}</span>
		<span class="text-end tabular-nums">{stats ? fmtInt(stats.textures) : '—'}</span>

		<span class="text-muted-foreground">{m.debug_programs()}</span>
		<span class="text-end tabular-nums">{stats ? stats.programs : '—'}</span>

		{#if jsHeapMB != null}
			<span class="text-muted-foreground">{m.debug_heap()}</span>
			<span class="text-end tabular-nums">{jsHeapMB.toFixed(0)} MB</span>
		{/if}

		<span class="text-muted-foreground">{m.debug_viewport()}</span>
		<span class="text-end tabular-nums">
			{#if stats}{stats.viewportW}×{stats.viewportH} @{stats.pixelRatio.toFixed(2)}×{:else}—{/if}
		</span>
	</div>

	<div class="mt-2 pt-2 border-t border-border/40">
		<div class="text-muted-foreground mb-1">{m.debug_objects_loaded({ total: totalObjects })}</div>
		<div class="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
			<span class="text-muted-foreground">{m.debug_planets()}</span>
			<span class="text-end tabular-nums">{fmtInt(counts.planets)}</span>
			<span class="text-muted-foreground">{m.debug_moons()}</span>
			<span class="text-end tabular-nums">{fmtInt(counts.moons)}</span>
			<span class="text-muted-foreground">{m.debug_probes()}</span>
			<span class="text-end tabular-nums">{fmtInt(counts.probes)}</span>
			<span class="text-muted-foreground">{m.debug_earth_sats()}</span>
			<span class="text-end tabular-nums">{fmtInt(counts.earthSatellites)}</span>
			<span class="text-muted-foreground">{m.debug_small_bodies()}</span>
			<span class="text-end tabular-nums">{fmtInt(counts.smallBodies)}</span>
			<span class="text-muted-foreground">{m.debug_promoted()}</span>
			<span class="text-end tabular-nums">{stats ? fmtInt(stats.promotedBodies) : '—'}</span>
		</div>
	</div>

	<div class="mt-2 pt-2 border-t border-border/40 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5">
		<span class="text-muted-foreground">{m.debug_focus()}</span>
		<span class="text-end truncate" title={stats?.focusedId}>
			{stats?.focusedName ?? stats?.focusedId ?? '—'}
		</span>
		<span class="text-muted-foreground">{m.debug_camera()}</span>
		<span class="text-end tabular-nums">{stats ? fmtAU(stats.cameraDistanceAU) : '—'}</span>
		<span class="text-muted-foreground">{m.debug_time_scale()}</span>
		<span class="text-end tabular-nums">{clock.timeScale.toLocaleString()}×</span>
		<span class="text-muted-foreground">{m.debug_jd()}</span>
		<span class="text-end tabular-nums">{clock.jd.toFixed(3)}</span>
	</div>

	<div class="mt-2 pt-2 border-t border-border/40 space-y-1">
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={settings.showSkyboxAlign}
				onchange={(e) => settings.setShowSkyboxAlign(e.currentTarget.checked)}
			/>
			<span>Skybox alignment tool</span>
		</label>
		<label class="flex items-center gap-2">
			<span>Max parts/zone</span>
			<input
				type="number"
				min="0"
				step="1"
				class="w-16 px-1 py-0.5 rounded bg-background border border-border/60 text-end tabular-nums"
				value={settings.maxPartsPerZone}
				onchange={(e) => settings.setMaxPartsPerZone(Number(e.currentTarget.value))}
			/>
			<span class="text-muted-foreground">0 = ∞, reload to apply</span>
		</label>
	</div>
</div>
