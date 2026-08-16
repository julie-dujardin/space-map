<!--
  Dev tool: runs the atmosphere benchmark in a visible frame, for eyeballing
  timing stability and tier spread on a device. Page-local: never writes the
  stored calibration. "full" measures every tier; "adaptive" replays boot
  calibration's ladder walk against the target budget.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { ACESFilmicToneMapping, WebGLRenderer } from 'three';
	import {
		gpuLabel,
		pickTier,
		runAtmosphereBenchmark,
		runAdaptiveAtmosphereBenchmark,
		type BenchmarkProgress,
		type BenchmarkReport
	} from '$lib/scene/perf/atmosphere-benchmark';
	import {
		ATMOSPHERE_QUALITY_PRESETS,
		heuristicAtmosphereTier,
		resolveAtmosphereTier
	} from '$lib/scene/objects/surface/atmosphere-quality';
	import { getSettings } from '$lib/state/settings.svelte';
	import { cappedPixelRatio } from '$lib/device';

	let canvas: HTMLCanvasElement;
	let renderer: WebGLRenderer | null = null;
	let abort: AbortController | null = null;

	let running = $state(false);
	let progress = $state<BenchmarkProgress | null>(null);
	let report = $state<BenchmarkReport | null>(null);
	let error = $state<string | null>(null);
	/** A tier qualifies while its shell-only rate stays at or above this. */
	let targetFps = $state(60);
	let gpu = $state('');

	const recommended = $derived(report ? pickTier(report, 1000 / targetFps) : null);
	const heuristic = heuristicAtmosphereTier();
	const settings = getSettings();

	async function run(mode: 'full' | 'adaptive' = 'full'): Promise<void> {
		if (!renderer || running) return;
		abort = new AbortController();
		running = true;
		error = null;
		report = null;
		try {
			report =
				mode === 'adaptive'
					? await runAdaptiveAtmosphereBenchmark(renderer, {
							budgetMs: 1000 / targetFps,
							startTier: heuristic,
							signal: abort.signal,
							onProgress: (p) => (progress = p)
						})
					: await runAtmosphereBenchmark(renderer, {
							signal: abort.signal,
							onProgress: (p) => (progress = p)
						});
		} catch (e) {
			if (!abort.signal.aborted) error = e instanceof Error ? e.message : String(e);
		} finally {
			running = false;
			progress = null;
		}
	}

	function resize(): void {
		renderer?.setSize(canvas.clientWidth, canvas.clientHeight, false);
	}

	function fmtMs(v: number): string {
		return `${v.toFixed(2)}ms`;
	}

	onMount(() => {
		try {
			renderer = new WebGLRenderer({ canvas, antialias: true });
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
			return;
		}
		renderer.setPixelRatio(cappedPixelRatio());
		renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
		// Match production's ACES tone mapping for a correct read; it doesn't affect measured cost.
		renderer.toneMapping = ACESFilmicToneMapping;
		gpu = gpuLabel(renderer);
		window.addEventListener('resize', resize);
		void run();

		return () => {
			abort?.abort();
			window.removeEventListener('resize', resize);
			renderer?.dispose();
		};
	});
</script>

<div class="page">
	<canvas bind:this={canvas}></canvas>

	<div class="panel">
		<div class="row header">
			<span class="title">Perf benchmark</span>
			<span class="buttons">
				<button type="button" class="run" disabled={running} onclick={() => run('full')}>
					{running ? 'running…' : 'full'}
				</button>
				<button type="button" class="run" disabled={running} onclick={() => run('adaptive')}>
					adaptive
				</button>
			</span>
		</div>

		<p class="info">{gpu}</p>
		{#if report}
			<p class="info">
				{report.drawWidth}×{report.drawHeight}px · ×{cappedPixelRatio().toFixed(1)} DPR
			</p>
		{/if}

		{#if error}
			<p class="error">{error}</p>
		{:else if running && progress}
			<p class="status">
				{progress.tier}
				({progress.tierIndex + 1}/{progress.tierCount}) · {progress.scenario} · {progress.phase}
				{progress.frame}/{progress.frames}
			</p>
		{/if}

		{#if report}
			<table>
				<thead>
					<tr><th>tier</th><th>view</th><th>median</th><th>p75</th><th>≈fps</th><th>batch</th></tr>
				</thead>
				<tbody>
					{#each report.tiers as t (t.tier)}
						{#if t.skipped}
							<tr>
								<td>{t.tier}</td>
								<td colspan="5" class="skipped">not measured</td>
							</tr>
						{:else}
							{#each [{ label: 'limb', s: t.limb }, { label: 'sky', s: t.sky }] as row (row.label)}
								<tr class:pick={t.tier === recommended}>
									<td>{row.label === 'limb' ? t.tier : ''}</td>
									<td>{row.label}</td>
									{#if row.s}
										<td>{fmtMs(row.s.medianMs)}</td>
										<td>{fmtMs(row.s.p75Ms)}</td>
										<td>{(1000 / row.s.medianMs).toFixed(0)}</td>
										<td>×{row.s.repeats}</td>
									{:else}
										<td colspan="4" class="skipped">
											{row.label === 'sky' && !ATMOSPHERE_QUALITY_PRESETS[t.tier].insideView
												? 'no inside view'
												: 'not measured'}
										</td>
									{/if}
								</tr>
							{/each}
						{/if}
					{/each}
				</tbody>
			</table>

			<div class="grid">
				<span class="lbl" title="Minimum shell-only frame rate a tier must sustain">Target</span>
				<input type="range" min="30" max="120" step="5" bind:value={targetFps} />
				<span class="val">{targetFps}fps</span>
			</div>

			<p class="verdict">
				measured → <strong>{recommended}</strong> · heuristic guess → {heuristic} · boot calibration →
				{settings.atmosphereCalibration?.tier ?? 'none'} · app currently resolves →
				{resolveAtmosphereTier(settings.atmosphereQuality)}{settings.atmosphereAutoTier
					? ` (governor learned ${settings.atmosphereAutoTier})`
					: ''}
			</p>
		{/if}

		<p class="note">
			Shell-only cost; production adds the rest of the scene + bloom, so real frame rates land below
			the ≈fps column.
		</p>
	</div>
</div>

<style>
	.page {
		position: fixed;
		inset: 0;
		background: #05070c;
	}
	canvas {
		width: 100%;
		height: 100%;
		display: block;
	}
	.panel {
		position: absolute;
		top: 12px;
		left: 12px;
		width: 340px;
		max-width: calc(100vw - 24px);
		max-height: calc(100vh - 24px);
		overflow-y: auto;
		background: rgba(15, 17, 21, 0.82);
		backdrop-filter: blur(6px);
		border: 1px solid #2b2f38;
		border-radius: 10px;
		padding: 12px 14px;
		color: #e7e9ee;
		font:
			12px/1.4 ui-monospace,
			monospace;
	}
	.row.header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}
	.buttons {
		display: flex;
		gap: 6px;
	}
	.title {
		font-weight: 600;
		font-size: 13px;
	}
	.run {
		background: #21262d;
		color: #c7ccd6;
		border: 1px solid #2b2f38;
		border-radius: 6px;
		padding: 3px 10px;
		cursor: pointer;
		font: inherit;
	}
	.run:hover:enabled {
		background: #2b313a;
		color: #e7e9ee;
	}
	.run:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.info {
		color: #9aa1ad;
		margin: 6px 0 0;
		overflow-wrap: anywhere;
	}
	.status {
		margin: 10px 0 0;
		color: #c7ccd6;
	}
	.error {
		margin: 10px 0 0;
		color: #ff7b72;
	}
	table {
		width: 100%;
		margin-top: 10px;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
	}
	th {
		text-align: start;
		color: #9aa1ad;
		font-weight: 400;
		border-bottom: 1px solid #2b2f3888;
		padding: 2px 6px 4px 0;
	}
	td {
		padding: 3px 6px 3px 0;
	}
	tr.pick td {
		color: #7ee787;
	}
	.skipped {
		color: #9aa1ad;
	}
	.grid {
		display: grid;
		grid-template-columns: auto 1fr auto;
		gap: 6px 10px;
		align-items: center;
		margin-top: 10px;
	}
	.lbl {
		color: #9aa1ad;
	}
	.val {
		text-align: end;
		font-variant-numeric: tabular-nums;
		width: 48px;
	}
	input[type='range'] {
		width: 100%;
		height: 12px;
	}
	.verdict {
		margin: 10px 0 0;
	}
	.verdict strong {
		color: #7ee787;
	}
	.note {
		margin: 10px 0 0;
		color: #9aa1ad;
	}
</style>
