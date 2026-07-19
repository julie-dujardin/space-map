import {
	DirectionalLight,
	Mesh,
	MeshStandardMaterial,
	PerspectiveCamera,
	Scene,
	SphereGeometry,
	Vector3,
	type WebGLRenderer
} from 'three';
import {
	applyAtmosphereQuality,
	ATMOSPHERE_PARAMS,
	buildAtmosphereNode,
	disposeAtmosphereNode
} from '$lib/scene/objects/surface/atmosphere';
import {
	ATMOSPHERE_QUALITY_PRESETS,
	type ResolvedAtmosphereTier
} from '$lib/scene/objects/surface/atmosphere-quality';

/**
 * Measures what each atmosphere quality tier actually costs on this device by
 * rendering the real shell shader and timing it with a forced GPU sync, so
 * tier selection can start from data instead of coarse device signals plus
 * reactive downgrades. Self-contained (no network assets) so it can run
 * against a hidden canvas during the app's initial data loads.
 */

/** Earth is the reference workload: mid-pack params, and the body users most
 *  often sit next to when a shell is prominent. */
const BENCH_BODY = 'naif-399';
const EARTH_RADIUS_KM = 6371;

// Camera just outside the shell, close enough that the shell's disc overflows
// the viewport height — the "shell prominent" case the perf governor guards.
const CAMERA_DIST = 1.6;
const SUN_DIR = new Vector3(0.55, 0.25, 0.8).normalize();

/** Cheap → costly, so blowing the abort threshold skips only costlier tiers. */
const BENCH_TIERS: ResolvedAtmosphereTier[] = ['low', 'medium', 'high', 'ultra'];

const WARMUP_FRAMES = 4;
const MEASURE_FRAMES = 12;
/** Per-sample GPU work target (ms): renders are batched up to this so
 *  Firefox's 1 ms performance.now() quantisation can't swamp a fast tier. */
const TARGET_SAMPLE_MS = 10;
const MAX_REPEATS = 16;

export interface TierSample {
	tier: ResolvedAtmosphereTier;
	/** Cost of one render, ms (CPU submit + GPU, serialised by the sync). */
	medianMs: number;
	p75Ms: number;
	/** Renders batched per timing sample for this tier. */
	repeats: number;
	/** Not measured: a cheaper tier already exceeded `abortAboveMs`. */
	skipped: boolean;
}

export interface BenchmarkReport {
	tiers: TierSample[];
	drawWidth: number;
	drawHeight: number;
}

export interface BenchmarkProgress {
	tier: ResolvedAtmosphereTier;
	tierIndex: number;
	tierCount: number;
	phase: 'warmup' | 'measure';
	frame: number;
	frames: number;
}

export interface BenchmarkOptions {
	tiers?: ResolvedAtmosphereTier[];
	/** Skip remaining (costlier) tiers once a median exceeds this. */
	abortAboveMs?: number;
	signal?: AbortSignal;
	onProgress?: (p: BenchmarkProgress) => void;
}

/** Costliest measured tier whose median fits the budget; low is the floor. */
export function pickTier(report: BenchmarkReport, budgetMs: number): ResolvedAtmosphereTier {
	let pick: ResolvedAtmosphereTier = 'low';
	for (const t of report.tiers) if (!t.skipped && t.medianMs <= budgetMs) pick = t.tier;
	return pick;
}

/** Unmasked GPU string where the browser exposes it — the persistence key for
 *  calibration results (a swapped GPU must invalidate old numbers). */
export function gpuLabel(renderer: WebGLRenderer): string {
	const gl = renderer.getContext();
	const ext = gl.getExtension('WEBGL_debug_renderer_info');
	return String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER));
}

export async function runAtmosphereBenchmark(
	renderer: WebGLRenderer,
	opts: BenchmarkOptions = {}
): Promise<BenchmarkReport> {
	const tiers = opts.tiers ?? BENCH_TIERS;
	const abortAboveMs = opts.abortAboveMs ?? 40;
	const { signal, onProgress } = opts;

	const gl = renderer.getContext();
	const scene = new Scene();
	const camera = new PerspectiveCamera(
		50,
		gl.drawingBufferWidth / Math.max(gl.drawingBufferHeight, 1),
		0.01,
		100
	);
	camera.position.set(0, 0, CAMERA_DIST);
	camera.lookAt(0, 0, 0);

	// The planet disc costs the same in every tier; it's here so the visible
	// bench frame reads as a sanity check (terminator matching the limb glow).
	const planetMaterial = new MeshStandardMaterial({ color: 0x777777, roughness: 1, metalness: 0 });
	const planet = new Mesh(new SphereGeometry(1, 64, 64), planetMaterial);
	planet.renderOrder = 1;
	scene.add(planet);
	const light = new DirectionalLight(0xffffff, 2);
	light.position.copy(SUN_DIR);
	scene.add(light);

	const params = ATMOSPHERE_PARAMS[BENCH_BODY];
	const atmoNode = buildAtmosphereNode(params, 1, EARTH_RADIUS_KM);
	const u = atmoNode.material.uniforms;
	(u.uSunDir.value as Vector3).copy(SUN_DIR);
	u.uSunIntensity.value = params.sunIntensity;
	scene.add(atmoNode.mesh);

	const pixel = new Uint8Array(4);
	const nextFrame = (): Promise<void> =>
		new Promise((resolve, reject) =>
			requestAnimationFrame(() =>
				signal?.aborted ? reject(new Error('benchmark aborted')) : resolve()
			)
		);
	// readPixels drains the GPU pipeline, so the wall clock brackets the full
	// cost of this frame's renders instead of just command submission.
	const sample = (repeats: number): number => {
		const t0 = performance.now();
		for (let i = 0; i < repeats; i++) renderer.render(scene, camera);
		gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
		return (performance.now() - t0) / repeats;
	};

	const results: TierSample[] = [];
	try {
		let skip = false;
		for (const [tierIndex, tier] of tiers.entries()) {
			if (skip) {
				results.push({ tier, medianMs: NaN, p75Ms: NaN, repeats: 0, skipped: true });
				continue;
			}
			applyAtmosphereQuality(atmoNode, ATMOSPHERE_QUALITY_PRESETS[tier]);
			const progress = (phase: 'warmup' | 'measure', frame: number, frames: number) =>
				onProgress?.({ tier, tierIndex, tierCount: tiers.length, phase, frame, frames });

			// Warmup absorbs the shader recompile (each tier is a new program) and
			// pipeline spin-up; the last warmup timing calibrates the batch size.
			let warm = 0;
			for (let f = 0; f < WARMUP_FRAMES; f++) {
				progress('warmup', f + 1, WARMUP_FRAMES);
				await nextFrame();
				warm = sample(1);
			}
			const repeats = Math.min(
				MAX_REPEATS,
				Math.max(1, Math.ceil(TARGET_SAMPLE_MS / Math.max(warm, 0.25)))
			);

			const samples: number[] = [];
			for (let f = 0; f < MEASURE_FRAMES; f++) {
				progress('measure', f + 1, MEASURE_FRAMES);
				await nextFrame();
				samples.push(sample(repeats));
			}
			samples.sort((a, b) => a - b);
			const medianMs = samples[Math.floor(samples.length / 2)];
			const p75Ms = samples[Math.floor(samples.length * 0.75)];
			results.push({ tier, medianMs, p75Ms, repeats, skipped: false });
			if (medianMs > abortAboveMs) skip = true;
		}
	} finally {
		scene.remove(planet, light, atmoNode.mesh);
		planet.geometry.dispose();
		planetMaterial.dispose();
		light.dispose();
		disposeAtmosphereNode(atmoNode);
	}

	return {
		tiers: results,
		drawWidth: gl.drawingBufferWidth,
		drawHeight: gl.drawingBufferHeight
	};
}
