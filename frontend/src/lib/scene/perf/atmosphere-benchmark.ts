import {
	BackSide,
	DirectionalLight,
	FrontSide,
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
	type AtmosphereParams,
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
 *
 * Two scenarios per tier: 'limb' (camera outside, shell disc overflowing the
 * viewport) and 'sky' (camera near the ground inside the shell — the BackSide
 * path, where the march covers every pixel). Sky is usually the worst case,
 * so the tier pick uses each tier's worse scenario. Runs as two passes (limb
 * across all tiers, then sky) so the visible run holds one viewpoint per pass.
 */

const EARTH_RADIUS_KM = 6371;

/** Normalised Henyey-Greenstein LUT in the shader's 3×128 quadratic-warp
 *  layout. Shader cost doesn't depend on table contents, so a synthetic phase
 *  keeps the bench free of the fetched atmospheres.json. */
function benchPhaseTable(g: number): number[] {
	const n = 128;
	const channel: number[] = [];
	for (let i = 0; i < n; i++) {
		const theta = Math.PI * (i / (n - 1)) ** 2;
		const mu = Math.cos(theta);
		channel.push(((1 / (4 * Math.PI)) * (1 - g * g)) / (1 + g * g - 2 * g * mu) ** 1.5);
	}
	return [...channel, ...channel, ...channel];
}

/** Earth-like reference workload: mid-pack params for the body users most
 *  often sit next to when a shell is prominent. Values only need to be
 *  representative — the timings measure the march, not the look. */
const BENCH_PARAMS: AtmosphereParams = {
	topAltitudeKm: 67,
	rayleighScatterPerKm: [5.8e-3, 13.6e-3, 33.1e-3],
	rayleighScaleHeightKm: 8.4,
	mieScatterPerKm: [4e-3, 4e-3, 4e-3],
	mieAbsorptionPerKm: [4e-4, 4e-4, 4e-4],
	mieScaleHeightKm: 1.2,
	miePhase: benchPhaseTable(0.75),
	absorptionPerKm: [0.65e-3, 1.881e-3, 0.085e-3],
	absorptionCenterKm: 25,
	absorptionWidthKm: 15,
	bakedCompensation: 1,
	multiScatterGain: 0.3,
	sunIntensity: 5,
	sunColor: [1, 1, 1]
};

const LIMB_CAMERA_DIST = 1.6;
/** ~3 km up: safely inside the shell without the surface clipping the view. */
const SKY_CAMERA_DIST = 1.0005;
const SUN_DIR = new Vector3(0.55, 0.25, 0.8).normalize();

/** Cheap → costly, so blowing the abort threshold skips only costlier tiers. */
const BENCH_TIERS: ResolvedAtmosphereTier[] = ['low', 'medium', 'high', 'ultra'];

const WARMUP_FRAMES = 4;
const MEASURE_FRAMES = 12;
/** Per-sample GPU work target (ms): renders are batched up to this so
 *  Firefox's 1 ms performance.now() quantisation can't swamp a fast tier. */
const TARGET_SAMPLE_MS = 10;
const MAX_REPEATS = 16;

export type BenchScenario = 'limb' | 'sky';

export interface ScenarioSample {
	/** Cost of one render, ms (CPU submit + GPU, serialised by the sync). */
	medianMs: number;
	p75Ms: number;
	/** Renders batched per timing sample. */
	repeats: number;
}

export interface TierSample {
	tier: ResolvedAtmosphereTier;
	limb: ScenarioSample | null;
	/** Null when the tier compiles without the inside view (nothing to march). */
	sky: ScenarioSample | null;
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
	scenario: BenchScenario;
	phase: 'warmup' | 'measure';
	frame: number;
	frames: number;
	/** Overall completion, 0..1. Jumps ahead when tiers are skipped. */
	fraction: number;
}

export interface BenchmarkOptions {
	tiers?: ResolvedAtmosphereTier[];
	/** Skip remaining (costlier) tiers once a worst-scenario median exceeds this. */
	abortAboveMs?: number;
	signal?: AbortSignal;
	onProgress?: (p: BenchmarkProgress) => void;
}

/** A tier's cost is its worse scenario, ms. NaN when it wasn't measured. */
export function tierWorstMs(t: TierSample): number {
	if (!t.limb) return NaN;
	return Math.max(t.limb.medianMs, t.sky?.medianMs ?? 0);
}

/** Costliest measured tier whose worst scenario fits the budget; low is the floor. */
export function pickTier(report: BenchmarkReport, budgetMs: number): ResolvedAtmosphereTier {
	let pick: ResolvedAtmosphereTier = 'low';
	for (const t of report.tiers) {
		const worst = tierWorstMs(t);
		if (!Number.isNaN(worst) && worst <= budgetMs) pick = t.tier;
	}
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
		0.005,
		100
	);

	// The planet disc costs the same in every tier; it's here so the visible
	// bench frame reads as a sanity check (terminator matching the limb glow).
	const planetMaterial = new MeshStandardMaterial({ color: 0x777777, roughness: 1, metalness: 0 });
	const planet = new Mesh(new SphereGeometry(1, 64, 64), planetMaterial);
	planet.renderOrder = 1;
	scene.add(planet);
	const light = new DirectionalLight(0xffffff, 2);
	light.position.copy(SUN_DIR);
	scene.add(light);

	const params = BENCH_PARAMS;
	const atmoNode = buildAtmosphereNode(params, 1, EARTH_RADIUS_KM);
	const u = atmoNode.material.uniforms;
	(u.uSunDir.value as Vector3).copy(SUN_DIR);
	u.uSunIntensity.value = params.sunIntensity;
	scene.add(atmoNode.mesh);

	// Mirrors the production inside-shell flip: BackSide + no depth so the sky
	// still rasterises with the camera inside the shell geometry.
	const setScenario = (s: BenchScenario): void => {
		const inside = s === 'sky';
		if (inside) {
			camera.position.set(0, SKY_CAMERA_DIST, 0);
			// A few degrees above the horizon: sky fills the frame, limb glow at
			// the bottom edge keeps the visible run interpretable.
			camera.lookAt(1, SKY_CAMERA_DIST + 0.1, 0);
		} else {
			camera.position.set(0, 0, LIMB_CAMERA_DIST);
			camera.lookAt(0, 0, 0);
		}
		atmoNode.material.side = inside ? BackSide : FrontSide;
		atmoNode.material.depthWrite = !inside;
		atmoNode.material.depthTest = !inside;
	};

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

	const measureScenario = async (
		tier: ResolvedAtmosphereTier,
		tierIndex: number,
		scenario: BenchScenario
	): Promise<ScenarioSample> => {
		setScenario(scenario);
		const stepFrames = WARMUP_FRAMES + MEASURE_FRAMES;
		const step = (scenario === 'sky' ? tiers.length : 0) + tierIndex;
		const progress = (phase: 'warmup' | 'measure', frame: number, frames: number) =>
			onProgress?.({
				tier,
				tierIndex,
				tierCount: tiers.length,
				scenario,
				phase,
				frame,
				frames,
				fraction:
					(step * stepFrames + (phase === 'measure' ? WARMUP_FRAMES : 0) + frame) /
					(tiers.length * 2 * stepFrames)
			});

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
		return {
			medianMs: samples[Math.floor(samples.length / 2)],
			p75Ms: samples[Math.floor(samples.length * 0.75)],
			repeats
		};
	};

	const limbBy = new Map<ResolvedAtmosphereTier, ScenarioSample | null>();
	const skyBy = new Map<ResolvedAtmosphereTier, ScenarioSample | null>();
	try {
		let skip = false;
		for (const [tierIndex, tier] of tiers.entries()) {
			if (skip) {
				limbBy.set(tier, null);
				continue;
			}
			applyAtmosphereQuality(atmoNode, ATMOSPHERE_QUALITY_PRESETS[tier]);
			const limb = await measureScenario(tier, tierIndex, 'limb');
			limbBy.set(tier, limb);
			if (limb.medianMs > abortAboveMs) skip = true;
		}
		skip = false;
		for (const [tierIndex, tier] of tiers.entries()) {
			const preset = ATMOSPHERE_QUALITY_PRESETS[tier];
			if (skip || !limbBy.get(tier) || !preset.insideView) {
				skyBy.set(tier, null);
				continue;
			}
			applyAtmosphereQuality(atmoNode, preset);
			const sky = await measureScenario(tier, tierIndex, 'sky');
			skyBy.set(tier, sky);
			if (sky.medianMs > abortAboveMs) skip = true;
		}
	} finally {
		scene.remove(planet, light, atmoNode.mesh);
		planet.geometry.dispose();
		planetMaterial.dispose();
		light.dispose();
		disposeAtmosphereNode(atmoNode);
	}

	return {
		tiers: tiers.map((tier) => {
			const limb = limbBy.get(tier) ?? null;
			return { tier, limb, sky: skyBy.get(tier) ?? null, skipped: !limb };
		}),
		drawWidth: gl.drawingBufferWidth,
		drawHeight: gl.drawingBufferHeight
	};
}
