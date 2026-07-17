<script lang="ts">
	import { onMount } from 'svelte';
	import type { SceneRenderer } from '$lib/scene/renderer';
	import type { AtmosphereParams } from '$lib/scene/objects/surface/atmosphere';
	import { getSettings } from '$lib/state/settings.svelte';

	interface Props {
		getRenderer: () => SceneRenderer | undefined;
	}

	let { getRenderer }: Props = $props();
	const settings = getSettings();

	// Mirrors of the layer-menu render toggles, so lighting experiments don't
	// need round-trips to a separate menu.
	const SCENE_TOGGLES: { label: string; get: () => boolean; set: (v: boolean) => void }[] = [
		{ label: 'Clouds', get: () => settings.showClouds, set: (v) => settings.setShowClouds(v) },
		{
			label: 'Atmospheres',
			get: () => settings.showAtmospheres,
			set: (v) => settings.setShowAtmospheres(v)
		},
		{
			label: 'High ambient',
			get: () => settings.highAmbient,
			set: (v) => settings.setHighAmbient(v)
		},
		{
			label: 'Realistic light',
			get: () => settings.realisticLighting,
			set: (v) => settings.setRealisticLighting(v)
		}
	];

	// Global multiplier on every direct-sunlight path (scene lights + shells) —
	// the scene-wide exposure experiment knob. Lives in the renderer so it
	// survives panel close/reopen.
	let sunX = $state(0);
	let sunSynced = false;

	// Coefficient sliders are log2 multipliers over the shipped params, so one
	// panel serves every body regardless of absolute magnitudes; gains and the
	// baked-texture compensation are absolute.
	let bodyId = $state<string | null>(null);
	let comp = $state(1);
	let sunIntensity = $state(5);
	let multiScatter = $state(0.3);
	let rayleighX = $state(0);
	let mieX = $state(0);
	let mieAbsX = $state(0);
	let absorberX = $state(0);
	let rayleighHX = $state(0);
	let mieHX = $state(0);
	let copied = $state(false);

	let shipped: AtmosphereParams | null = null;

	const LOG_SLIDERS: { label: string; get: () => number; set: (v: number) => void }[] = [
		{ label: 'Rayleigh β', get: () => rayleighX, set: (v) => (rayleighX = v) },
		{ label: 'Mie β', get: () => mieX, set: (v) => (mieX = v) },
		{ label: 'Mie absorb', get: () => mieAbsX, set: (v) => (mieAbsX = v) },
		{ label: 'Absorber β', get: () => absorberX, set: (v) => (absorberX = v) },
		{ label: 'Rayleigh H', get: () => rayleighHX, set: (v) => (rayleighHX = v) },
		{ label: 'Mie H', get: () => mieHX, set: (v) => (mieHX = v) }
	];

	function pushSun(): void {
		getRenderer()?.setSunIntensityScale(2 ** sunX);
	}

	function resetSun(): void {
		sunX = 0;
		pushSun();
	}

	function resolved(): AtmosphereParams | null {
		if (!shipped) return null;
		const scale3 = (v: [number, number, number], f: number): [number, number, number] => [
			v[0] * f,
			v[1] * f,
			v[2] * f
		];
		return {
			...shipped,
			rayleighScatterPerKm: scale3(shipped.rayleighScatterPerKm, 2 ** rayleighX),
			mieScatterPerKm: scale3(shipped.mieScatterPerKm, 2 ** mieX),
			mieAbsorptionPerKm: scale3(shipped.mieAbsorptionPerKm, 2 ** mieAbsX),
			absorptionPerKm: scale3(shipped.absorptionPerKm, 2 ** absorberX),
			rayleighScaleHeightKm: shipped.rayleighScaleHeightKm * 2 ** rayleighHX,
			mieScaleHeightKm: shipped.mieScaleHeightKm * 2 ** mieHX,
			bakedCompensation: comp,
			multiScatterGain: multiScatter,
			sunIntensity
		};
	}

	function push(): void {
		const p = resolved();
		if (p) getRenderer()?.setFocusedAtmosphereParams(p);
	}

	// Recover slider state from a body's live params so refocusing a tuned body
	// shows its actual values, not a stale shipped baseline.
	function syncFrom(current: AtmosphereParams, base: AtmosphereParams): void {
		const ratio = (a: number, b: number) => (b > 0 && a > 0 ? Math.log2(a / b) : 0);
		comp = current.bakedCompensation;
		sunIntensity = current.sunIntensity;
		multiScatter = current.multiScatterGain;
		rayleighX = ratio(current.rayleighScatterPerKm[0], base.rayleighScatterPerKm[0]);
		mieX = ratio(current.mieScatterPerKm[0], base.mieScatterPerKm[0]);
		mieAbsX = ratio(current.mieAbsorptionPerKm[0], base.mieAbsorptionPerKm[0]);
		absorberX = ratio(current.absorptionPerKm[1], base.absorptionPerKm[1]);
		rayleighHX = ratio(current.rayleighScaleHeightKm, base.rayleighScaleHeightKm);
		mieHX = ratio(current.mieScaleHeightKm, base.mieScaleHeightKm);
	}

	function resetShipped(): void {
		if (!shipped) return;
		syncFrom(shipped, shipped);
		push();
	}

	function setComp(v: number): void {
		comp = v;
		push();
	}

	async function copyJson(): Promise<void> {
		const p = resolved();
		if (!p) return;
		// miePhase is a 384-float offline table — pointless in a param dump.
		const rest = { ...p, miePhase: undefined };
		await navigator.clipboard.writeText(JSON.stringify(rest, null, '\t'));
		copied = true;
		setTimeout(() => (copied = false), 1200);
	}

	onMount(() => {
		let raf = 0;
		let lastPoll = 0;
		const tick = (now: number) => {
			raf = requestAnimationFrame(tick);
			if (now - lastPoll < 250) return;
			lastPoll = now;
			const r = getRenderer();
			if (!r) return;
			if (!sunSynced) {
				sunX = Math.log2(r.getSunIntensityScale());
				sunSynced = true;
			}
			const atmo = r.getFocusedAtmosphere();
			if (!atmo) {
				bodyId = null;
				shipped = null;
				return;
			}
			if (atmo.id !== bodyId) {
				bodyId = atmo.id;
				shipped = atmo.shipped;
				syncFrom(atmo.current, atmo.shipped);
			}
		};
		raf = requestAnimationFrame(tick);
		return () => cancelAnimationFrame(raf);
	});
</script>

<div
	class="absolute top-24 end-3 z-20 pointer-events-auto
		rounded-md bg-background/80 backdrop-blur-sm border border-border/60
		px-3 py-2 text-[11px] font-mono leading-tight text-foreground/90
		shadow-md w-[420px] select-text"
	role="group"
	aria-label="Lighting tuner debug controls"
>
	<div class="flex items-center justify-between mb-2">
		<span class="font-semibold text-foreground">Lighting tuner</span>
		<button
			type="button"
			class="text-muted-foreground hover:text-foreground underline"
			onclick={resetSun}
		>
			×1
		</button>
	</div>

	<div class="grid grid-cols-[auto_1fr_auto] gap-x-3 gap-y-1.5 items-center">
		<span class="text-muted-foreground" title="Multiplies every direct-sunlight path">
			Sun light
		</span>
		<input
			type="range"
			min="-3"
			max="3"
			step="0.05"
			bind:value={sunX}
			oninput={pushSun}
			class="w-full h-3"
		/>
		<span class="text-end tabular-nums w-14">×{(2 ** sunX).toFixed(2)}</span>
	</div>

	<div class="mt-2 pt-2 border-t border-border/40 grid grid-cols-2 gap-x-3 gap-y-1">
		{#each SCENE_TOGGLES as t (t.label)}
			<label class="flex items-center gap-2 cursor-pointer">
				<input type="checkbox" checked={t.get()} onchange={(e) => t.set(e.currentTarget.checked)} />
				<span>{t.label}</span>
			</label>
		{/each}
	</div>

	<div class="flex items-center justify-between mt-3 mb-2 pt-2 border-t border-border/40">
		<span class="font-semibold text-foreground">
			Atmosphere {bodyId ? `· ${bodyId}` : ''}
		</span>
		{#if bodyId}
			<div class="flex items-center gap-2">
				<button
					type="button"
					class="text-muted-foreground hover:text-foreground underline"
					onclick={resetShipped}
				>
					shipped
				</button>
				<button
					type="button"
					class="text-muted-foreground hover:text-foreground underline"
					onclick={copyJson}
				>
					{copied ? 'copied!' : 'copy JSON'}
				</button>
			</div>
		{/if}
	</div>

	{#if !bodyId}
		<div class="text-muted-foreground">Focused body has no atmosphere shell.</div>
	{:else}
		<div class="grid grid-cols-[auto_1fr_auto] gap-x-3 gap-y-1.5 items-center">
			<span class="text-muted-foreground" title="0 = pre-compensation look">Baked comp</span>
			<input
				type="range"
				min="0"
				max="1"
				step="0.01"
				value={comp}
				oninput={(e) => setComp(Number(e.currentTarget.value))}
				class="w-full h-3"
			/>
			<span class="text-end tabular-nums w-14">{comp.toFixed(2)}</span>

			<span class="text-muted-foreground">Atmo sun</span>
			<input
				type="range"
				min="0"
				max="40"
				step="0.1"
				value={sunIntensity}
				oninput={(e) => {
					sunIntensity = Number(e.currentTarget.value);
					push();
				}}
				class="w-full h-3"
			/>
			<span class="text-end tabular-nums w-14">{sunIntensity.toFixed(1)}</span>

			<span class="text-muted-foreground">Multi-scat</span>
			<input
				type="range"
				min="0"
				max="3"
				step="0.05"
				value={multiScatter}
				oninput={(e) => {
					multiScatter = Number(e.currentTarget.value);
					push();
				}}
				class="w-full h-3"
			/>
			<span class="text-end tabular-nums w-14">{multiScatter.toFixed(2)}</span>

			{#each LOG_SLIDERS as s (s.label)}
				<span class="text-muted-foreground">{s.label}</span>
				<input
					type="range"
					min="-4"
					max="4"
					step="0.05"
					value={s.get()}
					oninput={(e) => {
						s.set(Number(e.currentTarget.value));
						push();
					}}
					class="w-full h-3"
				/>
				<span class="text-end tabular-nums w-14">×{(2 ** s.get()).toFixed(2)}</span>
			{/each}
		</div>
	{/if}
</div>
