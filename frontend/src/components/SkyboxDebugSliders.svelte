<script lang="ts">
	import type { SceneRenderer } from '$lib/scene/renderer';
	import { onMount } from 'svelte';

	interface Props {
		getRenderer: () => SceneRenderer | undefined;
	}

	let { getRenderer }: Props = $props();

	let rxDeg = $state(0);
	let ryDeg = $state(0);
	let rzDeg = $state(0);
	let markersOn = $state(true);
	// Bumped once the parent's renderer becomes available — used to retrigger
	// the $effects that depend on `getRenderer()`. Without this, the effects
	// run once during mount (before the parent's onMount assigns `renderer`)
	// and never again until the user touches a slider.
	let rendererReady = $state(0);

	function apply(r: SceneRenderer | undefined): void {
		if (!r) return;
		r.setSkyboxAdjust(rxDeg, ryDeg, rzDeg);
		r.setSkyDebugMarkersVisible(markersOn);
	}

	$effect(() => {
		void rendererReady;
		apply(getRenderer());
	});

	$effect(() => {
		void rxDeg;
		void ryDeg;
		void rzDeg;
		void markersOn;
		apply(getRenderer());
	});

	onMount(() => {
		// Poll once per frame until the parent's renderer is ready, then bump
		// the trigger so the effects re-run with a live renderer.
		let raf = 0;
		const wait = () => {
			if (getRenderer()) {
				rendererReady++;
				return;
			}
			raf = requestAnimationFrame(wait);
		};
		raf = requestAnimationFrame(wait);
		return () => {
			cancelAnimationFrame(raf);
			// On unmount (debug toggled off), clear the markers but leave the
			// rotation adjustment intact in case the user toggles back on.
			getRenderer()?.setSkyDebugMarkersVisible(false);
		};
	});

	function reset(): void {
		rxDeg = 0;
		ryDeg = 0;
		rzDeg = 0;
	}
</script>

<div
	class="absolute top-3 end-3 z-20 pointer-events-auto
		rounded-md bg-background/80 backdrop-blur-sm border border-border/60
		px-3 py-2 text-[11px] font-mono leading-tight text-foreground/90
		shadow-md w-[480px] select-text"
	role="group"
	aria-label="Skybox alignment debug controls"
>
	<div class="flex items-center justify-between mb-2">
		<span class="font-semibold text-foreground">Skybox adjust</span>
		<button
			type="button"
			class="text-muted-foreground hover:text-foreground underline"
			onclick={reset}
		>
			reset
		</button>
	</div>

	<div class="grid grid-cols-[auto_1fr_auto] gap-x-3 gap-y-2 items-center">
		<span class="text-muted-foreground">X</span>
		<input type="range" min="-180" max="180" step="0.01" bind:value={rxDeg} class="w-full h-3" />
		<span class="text-end tabular-nums w-16">{rxDeg.toFixed(2)}°</span>

		<span class="text-muted-foreground">Y</span>
		<input type="range" min="-180" max="180" step="0.01" bind:value={ryDeg} class="w-full h-3" />
		<span class="text-end tabular-nums w-16">{ryDeg.toFixed(2)}°</span>

		<span class="text-muted-foreground">Z</span>
		<input type="range" min="-180" max="180" step="0.01" bind:value={rzDeg} class="w-full h-3" />
		<span class="text-end tabular-nums w-16">{rzDeg.toFixed(2)}°</span>
	</div>

	<label class="flex items-center gap-2 mt-2 cursor-pointer">
		<input type="checkbox" bind:checked={markersOn} />
		<span>Show sky landmarks</span>
	</label>
</div>
