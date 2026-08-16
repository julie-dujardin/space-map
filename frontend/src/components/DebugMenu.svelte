<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import XIcon from '@lucide/svelte/icons/x';
	import type { SceneRenderer } from '$lib/scene/renderer';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import type { SimClock } from '$lib/scene/state/clock.svelte';
	import { getSettings } from '$lib/state/settings.svelte';
	import {
		currentAtmosphereConfig,
		resolveAtmosphereTier
	} from '$lib/scene/objects/surface/atmosphere-quality';
	import * as m from '$lib/paraglide/messages.js';
	import type { PointingAxis, PointingSpec, PointingTarget } from '$lib/math/orientation';

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
	// performance.memory is a non-standard Chromium-only field; hide the row when absent.
	let jsHeapMB = $state<number | null>(null);

	// DEFAULT means "keep the body's current value"; all-default = no override.
	// NONE (secondary only) drops the secondary constraint.
	const DEFAULT = 'default';
	const NONE = 'none';
	const POINTING_AXES: PointingAxis[] = ['+x', '-x', '+y', '-y', '+z', '-z'];
	const POINTING_TARGETS: PointingTarget[] = ['parent', 'sun', 'velocity'];
	let pointingSupported = $state(false);
	let pointingFocusedId = $state<string | undefined>(undefined);
	let overrideMode = $state(false);
	// The body's natural attitude; labels the "default (…)" options and fills
	// any field left on DEFAULT.
	let base = $state<PointingSpec>({ primary: { axis: '-y', target: 'parent' } });
	let primaryAxisSel = $state<string>(DEFAULT);
	let primaryTargetSel = $state<string>(DEFAULT);
	let secondaryAxisSel = $state<string>(DEFAULT);
	let secondaryTargetSel = $state<string>(DEFAULT);

	function resetSelections(): void {
		primaryAxisSel = DEFAULT;
		primaryTargetSel = DEFAULT;
		secondaryAxisSel = DEFAULT;
		secondaryTargetSel = DEFAULT;
	}

	function setOverrideMode(on: boolean): void {
		overrideMode = on;
		if (!on) {
			resetSelections();
			getRenderer()?.setFocusedPointing(null);
		}
	}

	function applyPointing(): void {
		const r = getRenderer();
		if (!r) return;
		// No field changed → no override.
		if (
			primaryAxisSel === DEFAULT &&
			primaryTargetSel === DEFAULT &&
			secondaryAxisSel === DEFAULT &&
			secondaryTargetSel === DEFAULT
		) {
			r.setFocusedPointing(null);
			return;
		}
		const spec: PointingSpec = {
			primary: {
				axis: (primaryAxisSel === DEFAULT ? base.primary.axis : primaryAxisSel) as PointingAxis,
				target: (primaryTargetSel === DEFAULT
					? base.primary.target
					: primaryTargetSel) as PointingTarget
			}
		};
		if (secondaryAxisSel !== NONE && secondaryTargetSel !== NONE) {
			const axis = (secondaryAxisSel === DEFAULT ? base.secondary?.axis : secondaryAxisSel) as
				| PointingAxis
				| undefined;
			const target = (
				secondaryTargetSel === DEFAULT ? base.secondary?.target : secondaryTargetSel
			) as PointingTarget | undefined;
			if (axis && target) spec.secondary = { axis, target };
		}
		r.setFocusedPointing(spec);
	}

	// Read both signals into locals first: `&&` short-circuiting would drop
	// one as a reactive dependency.
	$effect(() => {
		const supported = pointingSupported;
		const on = overrideMode;
		const r = getRenderer();
		r?.setPointingAxesVisible(supported && on);
		return () => r?.setPointingAxesVisible(false);
	});

	// Untrack the reapply call: it reads live per-frame scene state that would
	// otherwise re-fire this effect every frame and spin the texture reload.
	// Skip the first run so opening the panel is a no-op.
	let layersInit = false;
	$effect(() => {
		const _deps = [
			settings.showShapeMesh,
			settings.showSurfaceTexture,
			settings.showDisplacement,
			settings.showSelfShadow
		];
		void _deps;
		if (!layersInit) {
			layersInit = true;
			return;
		}
		untrack(() => getRenderer()?.reapplyBodyLayers());
	});

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
		// ~250ms poll keeps the panel responsive without measurable render cost.
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

			const fp = r.getFocusedPointing();
			pointingSupported = !!fp?.supported;
			if (fp) base = fp.base;
			// New focus: drop any in-progress override selections back to default.
			if (stats.focusedId !== pointingFocusedId) {
				pointingFocusedId = stats.focusedId;
				resetSelections();
			}
		};
		raf = requestAnimationFrame(tick);
		return () => cancelAnimationFrame(raf);
	});

	let totalObjects = $derived(
		counts.planets + counts.moons + counts.probes + counts.earthSatellites + counts.smallBodies
	);

	// currentAtmosphereConfig reads the settings runes, so this tracks both
	// the tier preset and session overrides.
	let atmoTier = $derived(resolveAtmosphereTier(settings.atmosphereQuality));
	let atmoCfg = $derived(currentAtmosphereConfig());
</script>

<div
	class="absolute top-16 start-4 z-10 pointer-events-auto
		rounded-md bg-background/80 backdrop-blur-sm border border-border/60
		px-3 py-2 text-[11px] font-mono leading-tight text-foreground/90
		shadow-md max-w-[260px] select-text"
	role="status"
	aria-live="off"
>
	<div class="flex items-start justify-between gap-2 mb-1">
		<div class="font-semibold text-foreground">{m.debug_title()}</div>
		<button
			type="button"
			class="-mt-0.5 -me-1 inline-flex items-center justify-center
				w-5 h-5 rounded hover:bg-accent transition-colors cursor-pointer"
			onclick={() => settings.setShowDebugInfo(false)}
			aria-label={m.close()}
		>
			<XIcon class="size-3.5" />
		</button>
	</div>

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
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={settings.showHaloDebug}
				onchange={(e) => settings.setShowHaloDebug(e.currentTarget.checked)}
			/>
			<span>Label halo overlay</span>
		</label>
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={settings.showLightingTuner}
				onchange={(e) => settings.setShowLightingTuner(e.currentTarget.checked)}
			/>
			<span>Lighting tuner</span>
		</label>
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={settings.overexposeRings}
				onchange={(e) => settings.setOverexposeRings(e.currentTarget.checked)}
			/>
			<span>
				Overexpose rings
				<span class="text-muted-foreground">(full stored dynamic range)</span>
			</span>
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

	<div class="mt-2 pt-2 border-t border-border/40 space-y-1">
		<div class="text-muted-foreground">Focused body layers</div>
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={settings.showShapeMesh}
				onchange={(e) => settings.setShowShapeMesh(e.currentTarget.checked)}
			/>
			<span>Shape mesh <span class="text-muted-foreground">(off → triaxial sphere)</span></span>
		</label>
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={settings.showSurfaceTexture}
				onchange={(e) => settings.setShowSurfaceTexture(e.currentTarget.checked)}
			/>
			<span>Surface texture</span>
		</label>
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={settings.showDisplacement}
				onchange={(e) => settings.setShowDisplacement(e.currentTarget.checked)}
			/>
			<span>Displacement (DEM)</span>
		</label>
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={settings.showSelfShadow}
				onchange={(e) => settings.setShowSelfShadow(e.currentTarget.checked)}
			/>
			<span>Self-shadow</span>
		</label>
	</div>

	<div class="mt-2 pt-2 border-t border-border/40 space-y-1">
		<div class="text-muted-foreground">
			Atmosphere quality ({settings.atmosphereQuality === 'auto' ? `auto → ${atmoTier}` : atmoTier})
			<span class="opacity-70">— overrides last until reload</span>
		</div>
		{#if settings.atmosphereAutoTier}
			<div class="flex items-center gap-2">
				<span class="text-muted-foreground flex-1"
					>perf-capped at {settings.atmosphereAutoTier}</span
				>
				<button
					type="button"
					class="px-1.5 py-0.5 rounded bg-background border border-border/60 hover:bg-accent
						transition-colors cursor-pointer"
					onclick={() => settings.setAtmosphereAutoTier(null)}
				>
					reset
				</button>
			</div>
		{/if}
		<label class="flex items-center gap-2">
			<span class="flex-1">March steps</span>
			<input
				type="number"
				min="4"
				max="64"
				step="1"
				class="w-14 px-1 py-0.5 rounded bg-background border border-border/60 text-end tabular-nums"
				value={atmoCfg.primarySteps}
				onchange={(e) =>
					settings.setAtmoQualityOverrides({
						primarySteps: Math.max(4, Math.min(64, Math.floor(Number(e.currentTarget.value)) || 4))
					})}
			/>
		</label>
		<label class="flex items-center gap-2">
			<span class="flex-1">Sun steps</span>
			<input
				type="number"
				min="1"
				max="16"
				step="1"
				class="w-14 px-1 py-0.5 rounded bg-background border border-border/60 text-end tabular-nums"
				value={atmoCfg.lightSteps}
				onchange={(e) =>
					settings.setAtmoQualityOverrides({
						lightSteps: Math.max(1, Math.min(16, Math.floor(Number(e.currentTarget.value)) || 1))
					})}
			/>
		</label>
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={atmoCfg.eclipseShadows}
				onchange={(e) =>
					settings.setAtmoQualityOverrides({ eclipseShadows: e.currentTarget.checked })}
			/>
			<span>Eclipse shadows</span>
		</label>
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={atmoCfg.ringShadows}
				onchange={(e) => settings.setAtmoQualityOverrides({ ringShadows: e.currentTarget.checked })}
			/>
			<span>Ring shadows</span>
		</label>
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={atmoCfg.insideView}
				onchange={(e) => settings.setAtmoQualityOverrides({ insideView: e.currentTarget.checked })}
			/>
			<span>Inside view <span class="text-muted-foreground">(sky + depth prepass)</span></span>
		</label>
		<label class="flex items-center gap-2 cursor-pointer">
			<input
				type="checkbox"
				checked={atmoCfg.sunTint}
				onchange={(e) => settings.setAtmoQualityOverrides({ sunTint: e.currentTarget.checked })}
			/>
			<span>Sun tint <span class="text-muted-foreground">(sunset light + disc chroma)</span></span>
		</label>
	</div>

	{#if pointingSupported}
		<div class="mt-2 pt-2 border-t border-border/40 space-y-1">
			<label class="flex items-center gap-2 cursor-pointer">
				<input
					type="checkbox"
					checked={overrideMode}
					onchange={(e) => setOverrideMode(e.currentTarget.checked)}
				/>
				<span>Attitude override</span>
			</label>
			{#if overrideMode}
				<div>
					<div class="text-muted-foreground">primary</div>
					<div class="flex items-center gap-1">
						<select
							class="flex-1 min-w-0 px-1 py-0.5 rounded bg-background border border-border/60"
							value={primaryAxisSel}
							onchange={(e) => {
								primaryAxisSel = e.currentTarget.value;
								applyPointing();
							}}
						>
							<option value={DEFAULT}>dft ({base.primary.axis})</option>
							{#each POINTING_AXES as axis (axis)}<option value={axis}>{axis}</option>{/each}
						</select>
						<span class="text-muted-foreground">→</span>
						<select
							class="flex-1 min-w-0 px-1 py-0.5 rounded bg-background border border-border/60"
							value={primaryTargetSel}
							onchange={(e) => {
								primaryTargetSel = e.currentTarget.value;
								applyPointing();
							}}
						>
							<option value={DEFAULT}>dft ({base.primary.target})</option>
							{#each POINTING_TARGETS as t (t)}<option value={t}>{t}</option>{/each}
						</select>
					</div>
				</div>
				<div>
					<div class="text-muted-foreground">secondary</div>
					<div class="flex items-center gap-1">
						<select
							class="flex-1 min-w-0 px-1 py-0.5 rounded bg-background border border-border/60"
							value={secondaryAxisSel}
							onchange={(e) => {
								secondaryAxisSel = e.currentTarget.value;
								applyPointing();
							}}
						>
							<option value={DEFAULT}>dft ({base.secondary?.axis ?? NONE})</option>
							<option value={NONE}>none</option>
							{#each POINTING_AXES as axis (axis)}<option value={axis}>{axis}</option>{/each}
						</select>
						<span class="text-muted-foreground">→</span>
						<select
							class="flex-1 min-w-0 px-1 py-0.5 rounded bg-background border border-border/60"
							value={secondaryTargetSel}
							onchange={(e) => {
								secondaryTargetSel = e.currentTarget.value;
								applyPointing();
							}}
						>
							<option value={DEFAULT}>dft ({base.secondary?.target ?? NONE})</option>
							<option value={NONE}>none</option>
							{#each POINTING_TARGETS as t (t)}<option value={t}>{t}</option>{/each}
						</select>
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>
