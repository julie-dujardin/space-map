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
 * Measures what atmosphere quality tiers actually cost on this device by
 * rendering the real shell shader with a forced GPU sync, so tier selection
 * starts from data instead of device-signal heuristics. Self-contained, so it
 * can run against a hidden canvas during the app's initial data loads.
 *
 * Two scenarios per tier: 'limb' (camera outside, disc overflowing the
 * viewport) and 'sky' (camera inside the shell, BackSide path, march covers
 * every pixel) — a tier's cost is its worse scenario, usually sky.
 *
 * {@link runAtmosphereBenchmark} sweeps every tier for the debug page.
 * {@link runAdaptiveAtmosphereBenchmark} measures only the tiers that decide
 * the pick against a budget, for boot calibration.
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

/** Cheap → costly; both drivers rely on cost rising monotonically with tier. */
const BENCH_TIERS: ResolvedAtmosphereTier[] = ['low', 'medium', 'high', 'ultra'];

const WARMUP_FRAMES = 4;
const MEASURE_FRAMES = 12;
/** Per-sample GPU work target (ms): renders are batched up to this so
 *  Firefox's 1 ms performance.now() quantisation can't swamp a fast tier. */
const TARGET_SAMPLE_MS = 10;
const MAX_REPEATS = 16;
/** Samples before an early verdict is allowed. */
const MIN_DECIDE_FRAMES = 5;

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
	/** Null when unmeasured (cutoff skip, or its sky already failed the budget). */
	limb: ScenarioSample | null;
	/** Null when the tier compiles without the inside view, or wasn't measured. */
	sky: ScenarioSample | null;
	/** Neither scenario ran: the cutoff/budget made the tier irrelevant. */
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

export interface AdaptiveBenchmarkOptions {
	/** Frame budget the picked tier must fit in its worse scenario. */
	budgetMs: number;
	/** Ladder entry point — the better the guess, the shorter the walk. */
	startTier?: ResolvedAtmosphereTier;
	tiers?: ResolvedAtmosphereTier[];
	signal?: AbortSignal;
	onProgress?: (p: BenchmarkProgress) => void;
}

/** A tier's cost is its worse measured scenario, ms. NaN when neither ran. */
export function tierWorstMs(t: TierSample): number {
	if (!t.limb && !t.sky) return NaN;
	return Math.max(t.limb?.medianMs ?? 0, t.sky?.medianMs ?? 0);
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

interface MeasureOptions {
	/** Stop sampling once the verdict against this budget is decisive; a
	 *  near-budget tier still runs the full frame count for the tight estimate. */
	decideMs?: number;
	onFrame?: (phase: 'warmup' | 'measure', frame: number) => void;
}

interface BenchHarness {
	measure(
		tier: ResolvedAtmosphereTier,
		scenario: BenchScenario,
		opts?: MeasureOptions
	): Promise<ScenarioSample>;
	dispose(): void;
}

function createHarness(renderer: WebGLRenderer, signal?: AbortSignal): BenchHarness {
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

	const measure = async (
		tier: ResolvedAtmosphereTier,
		scenario: BenchScenario,
		{ decideMs, onFrame }: MeasureOptions = {}
	): Promise<ScenarioSample> => {
		applyAtmosphereQuality(atmoNode, ATMOSPHERE_QUALITY_PRESETS[tier]);
		setScenario(scenario);

		// Warmup absorbs the shader recompile (each tier is a new program) and
		// pipeline spin-up; the last warmup timing calibrates the batch size.
		let warm = 0;
		for (let f = 0; f < WARMUP_FRAMES; f++) {
			onFrame?.('warmup', f + 1);
			await nextFrame();
			warm = sample(1);
		}
		const repeats = Math.min(
			MAX_REPEATS,
			Math.max(1, Math.ceil(TARGET_SAMPLE_MS / Math.max(warm, 0.25)))
		);

		const samples: number[] = [];
		const stats = (): { medianMs: number; p75Ms: number } => {
			const s = [...samples].sort((a, b) => a - b);
			return { medianMs: s[Math.floor(s.length / 2)], p75Ms: s[Math.floor(s.length * 0.75)] };
		};
		for (let f = 0; f < MEASURE_FRAMES; f++) {
			onFrame?.('measure', f + 1);
			await nextFrame();
			samples.push(sample(repeats));
			if (decideMs !== undefined && samples.length >= MIN_DECIDE_FRAMES) {
				const { medianMs, p75Ms } = stats();
				if (medianMs > decideMs * 1.4 || p75Ms < decideMs * 0.7) break;
			}
		}
		return { ...stats(), repeats };
	};

	const dispose = (): void => {
		scene.remove(planet, light, atmoNode.mesh);
		planet.geometry.dispose();
		planetMaterial.dispose();
		light.dispose();
		disposeAtmosphereNode(atmoNode);
	};

	return { measure, dispose };
}

function buildReport(
	renderer: WebGLRenderer,
	tiers: ResolvedAtmosphereTier[],
	limbBy: Map<ResolvedAtmosphereTier, ScenarioSample | null>,
	skyBy: Map<ResolvedAtmosphereTier, ScenarioSample | null>
): BenchmarkReport {
	const gl = renderer.getContext();
	return {
		tiers: tiers.map((tier) => {
			const limb = limbBy.get(tier) ?? null;
			const sky = skyBy.get(tier) ?? null;
			return { tier, limb, sky, skipped: !limb && !sky };
		}),
		drawWidth: gl.drawingBufferWidth,
		drawHeight: gl.drawingBufferHeight
	};
}

/** Full sweep, for the debug page: every tier in both scenarios, no early
 *  sample exits — the point is eyeballing the whole spread. */
export async function runAtmosphereBenchmark(
	renderer: WebGLRenderer,
	opts: BenchmarkOptions = {}
): Promise<BenchmarkReport> {
	const tiers = opts.tiers ?? BENCH_TIERS;
	const abortAboveMs = opts.abortAboveMs ?? 40;
	const { signal, onProgress } = opts;
	const harness = createHarness(renderer, signal);

	const stepFrames = WARMUP_FRAMES + MEASURE_FRAMES;
	const measure = (tierIndex: number, scenario: BenchScenario): Promise<ScenarioSample> =>
		harness.measure(tiers[tierIndex], scenario, {
			onFrame: (phase, frame) =>
				onProgress?.({
					tier: tiers[tierIndex],
					tierIndex,
					tierCount: tiers.length,
					scenario,
					phase,
					frame,
					frames: phase === 'measure' ? MEASURE_FRAMES : WARMUP_FRAMES,
					fraction:
						(((scenario === 'sky' ? tiers.length : 0) + tierIndex) * stepFrames +
							(phase === 'measure' ? WARMUP_FRAMES : 0) +
							frame) /
						(tiers.length * 2 * stepFrames)
				})
		});

	const limbBy = new Map<ResolvedAtmosphereTier, ScenarioSample | null>();
	const skyBy = new Map<ResolvedAtmosphereTier, ScenarioSample | null>();
	try {
		let skip = false;
		for (const [tierIndex, tier] of tiers.entries()) {
			if (skip) {
				limbBy.set(tier, null);
				continue;
			}
			const limb = await measure(tierIndex, 'limb');
			limbBy.set(tier, limb);
			if (limb.medianMs > abortAboveMs) skip = true;
		}
		skip = false;
		for (const [tierIndex, tier] of tiers.entries()) {
			if (skip || !limbBy.get(tier) || !ATMOSPHERE_QUALITY_PRESETS[tier].insideView) {
				skyBy.set(tier, null);
				continue;
			}
			const sky = await measure(tierIndex, 'sky');
			skyBy.set(tier, sky);
			if (sky.medianMs > abortAboveMs) skip = true;
		}
	} finally {
		harness.dispose();
	}

	return buildReport(renderer, tiers, limbBy, skyBy);
}

/**
 * Boot-calibration driver: finds the costliest tier fitting `budgetMs`
 * without sweeping the ladder. Starts at `startTier`, climbs while tiers fit
 * or descends until one does. Sky (usually the worse scenario) runs first, so
 * a tier failing there skips its limb pass, and sampling stops early on
 * decisive verdicts. The floor tier isn't measured when everything above
 * already failed — it gets picked regardless. Unmeasured tiers come back with
 * null scenarios.
 */
export async function runAdaptiveAtmosphereBenchmark(
	renderer: WebGLRenderer,
	opts: AdaptiveBenchmarkOptions
): Promise<BenchmarkReport> {
	const tiers = opts.tiers ?? BENCH_TIERS;
	const { budgetMs, signal, onProgress } = opts;
	const startIdx = Math.max(0, tiers.indexOf(opts.startTier ?? tiers[tiers.length - 1]));
	const harness = createHarness(renderer, signal);

	// Progress assumes the walk ends with the current tier — usually true, and
	// the honest alternative (worst-case remainder) parks the bar at ~20% on
	// the common one-tier run. Extra tiers slow the bar asymptotically instead;
	// the max() keeps it monotonic for the determinate loading bar.
	const stepFrames = WARMUP_FRAMES + MEASURE_FRAMES;
	let framesDone = 0;
	let fraction = 0;

	const measure = (
		tierIndex: number,
		scenario: BenchScenario,
		scenariosAfter: number
	): Promise<ScenarioSample> =>
		harness.measure(tiers[tierIndex], scenario, {
			decideMs: budgetMs,
			onFrame: (phase, frame) => {
				if (!onProgress) return;
				framesDone++;
				const doneInScenario = (phase === 'measure' ? WARMUP_FRAMES : 0) + frame;
				const remaining = stepFrames - doneInScenario + scenariosAfter * stepFrames;
				fraction = Math.max(fraction, framesDone / (framesDone + remaining));
				onProgress({
					tier: tiers[tierIndex],
					tierIndex,
					tierCount: tiers.length,
					scenario,
					phase,
					frame,
					frames: phase === 'measure' ? MEASURE_FRAMES : WARMUP_FRAMES,
					fraction
				});
			}
		});

	const limbBy = new Map<ResolvedAtmosphereTier, ScenarioSample | null>();
	const skyBy = new Map<ResolvedAtmosphereTier, ScenarioSample | null>();
	const measureTier = async (i: number): Promise<boolean> => {
		const tier = tiers[i];
		if (ATMOSPHERE_QUALITY_PRESETS[tier].insideView) {
			const sky = await measure(i, 'sky', 1);
			skyBy.set(tier, sky);
			if (sky.medianMs > budgetMs) return false; // limb can't rescue the worst case
		}
		const limb = await measure(i, 'limb', 0);
		limbBy.set(tier, limb);
		return limb.medianMs <= budgetMs;
	};

	try {
		if (await measureTier(startIdx)) {
			for (let i = startIdx + 1; i < tiers.length && (await measureTier(i)); i++);
		} else {
			for (let i = startIdx - 1; i >= 1 && !(await measureTier(i)); i--);
		}
	} finally {
		harness.dispose();
	}

	return buildReport(renderer, tiers, limbBy, skyBy);
}
