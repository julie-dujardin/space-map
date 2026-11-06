/**
 * Dust in front of the stars, from any viewpoint.
 *
 * A star's catalogue magnitude has the Sun's dust in it. So each star takes the
 * change of column between the camera and the Sun:
 *
 *   m = mag + K_G · (A(camera→star) − A(Sun→star))
 *
 * On a device that can afford it, the two columns come from two sky maps, made
 * by one pass. One has its origin at the Sun and never changes. The other has
 * its origin near the camera. With the camera near the Sun, that map is the Sun
 * map itself, so the change is exactly zero and the sky from the Sun does not
 * change.
 *
 * A map refreshes only when the camera has moved far enough. It fills a second
 * texture over a few frames and then takes over, so a refresh has no visible
 * steps. With nothing moving, this does no work at all.
 *
 * A device with no sky map gets one change per node, from CPU rays through the
 * `low` nest. The `low` nest also finds the nearest dust for the refresh rule.
 */

import type { StarUniforms } from '$lib/scene/starfield/material';
import { SwitchFade } from '$lib/scene/visibility/switch-fade';
import { inSceneCredits, type ExtrasolarCredit } from '$lib/fetch/extrasolar/files';
import type { Texture, WebGLRenderer } from 'three';
import { GpuLoad, type LoadPhase } from './gpu-load';
import { DUST_MAP_LAYERS, DUST_MAP_SIZE } from './layout';
import { DustMarch, NestTextures, SkyMap, canMarch } from './march';
import {
	columnBetween,
	fetchNestLevels,
	fetchNestMetadata,
	nestCredits,
	treeToNest,
	type NestLevel,
	type NestMetadata,
	type NestTier
} from './nest';
import { nodeShift, sampleNode, type NodeSample } from './node-shift';
import type { Vec3 } from './octahedral';
import { RefreshPacer, nearestStructure, refreshReach } from './refresh';

/** How the stars read the dust on this device. */
export interface DustPlan {
	mode: 'map' | 'node';
	/** The nest on the GPU, for a map. */
	nest: NestTier;
	/** Passes that make one map. */
	passes: number;
}

const FADE_MS = 800;
const SUN: Vec3 = [0, 0, 0];
const NO_CREDITS: readonly ExtrasolarCredit[] = [];

/** Where a pass samples inside a step. All passes together cut the step into
 *  even parts, and the first few already cover it. */
export function passJitter(pass: number, passes: number): number {
	let f = 0.5 / passes;
	let bit = 0.5;
	for (let n = pass; n > 0; n >>= 1, bit /= 2) if (n & 1) f += bit;
	return f;
}

const distance = (a: Vec3, b: Vec3): number => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

/** A map being made. */
interface MapJob {
	origin: Vec3;
	reach: number;
	pass: number;
}

/** The `low` nest for the CPU, and the GPU nest of a `high` map plan. */
type NestLoad = [readonly NestLevel[], readonly NestLevel[] | null];

export class StarDust {
	/** False draws the stars as the catalogue has them, for a comparison. */
	private enabled = true;
	private plan: DustPlan;
	private readonly load: GpuLoad<NestMetadata, NestLoad>;
	/** The `low` nest, for CPU rays. */
	private cpu: readonly NestLevel[] | null = null;
	private cpuFetch: Promise<readonly NestLevel[]> | null = null;
	private gpu: NestTextures | null = null;
	private march: DustMarch | null = null;
	private sunMap: SkyMap | null = null;
	/** The map stars read, and the one being made. */
	private front: SkyMap | null = null;
	private back: SkyMap | null = null;
	private sunPasses = 0;
	private sunReach = 0;
	private frontReach = 0;
	private job: MapJob | null = null;
	/** The camera has left the reach of the origin in use. */
	private stale = false;
	/** Where the stars' columns start. The Sun, until the camera leaves its reach. */
	private origin: Vec3 = SUN;
	private readonly pacer = new RefreshPacer();
	private readonly fade = new SwitchFade(false, FADE_MS);
	private sceneCredits: ExtrasolarCredit[] | null = null;
	/** The last frame made a pass or moved the origin: the next frame's length
	 *  is what that cost. */
	private marched = false;
	/** This device could not make a sky map, so the session goes without one. */
	private mapFailed = false;
	private passes = 0;
	private refreshes = 0;
	/** Rises when the origin moves, so a node knows its shift is old. */
	epoch = 0;
	private readonly columnMap: { map: Texture; origin: Vec3 } = { map: null as never, origin: SUN };

	constructor(
		private readonly renderer: WebGLRenderer,
		plan: DustPlan,
		private readonly onChange: () => void
	) {
		this.plan = this.fit(plan);
		this.load = new GpuLoad(
			renderer,
			'dust',
			'the nest',
			{
				metadata: fetchNestMetadata,
				received: (_meta, [cpu, gpu]) => this.received(cpu, gpu),
				release: (live) => this.release(live),
				reset: () => this.reset()
			},
			onChange
		);
	}

	/** The device's plan, with the map only where the context can draw one. */
	private fit(plan: DustPlan): DustPlan {
		const noMap = this.mapFailed || !canMarch(this.renderer);
		return plan.mode === 'map' && noMap ? { ...plan, mode: 'node' } : plan;
	}

	/** The tier changed. The nest tier matters to a map only. */
	setPlan(plan: DustPlan): void {
		const fitted = this.fit(plan);
		const changed =
			fitted.mode !== this.plan.mode || (fitted.mode === 'map' && fitted.nest !== this.plan.nest);
		this.plan = fitted;
		if (changed) this.load.restart(true);
	}

	/** Back to the Sun with no map, for a load that starts again. */
	private reset(): void {
		this.job = null;
		this.stale = false;
		this.marched = false;
		this.origin = SUN;
		this.sunPasses = 0;
		this.epoch++;
	}

	/** Free the GPU objects. A lost context took them already. */
	private release(live: boolean): void {
		if (live) {
			this.sunMap?.dispose();
			this.front?.dispose();
			this.back?.dispose();
			this.march?.dispose();
			this.gpu?.dispose();
		}
		this.sunMap = this.front = this.back = this.march = this.gpu = null;
	}

	get nodeMode(): boolean {
		return this.plan.mode === 'node' && this.load.phase === 'ready';
	}

	/** The nest on the GPU, once a map can use it. */
	get marchNest(): NestTextures | null {
		return this.load.phase === 'ready' && this.march ? this.gpu : null;
	}

	/** The map of the columns from the camera's side, and its origin: the Sun's
	 *  own near the Sun. Null until the Sun's map is made, and without maps. Light
	 *  that has no dust of the Sun's in it, as a nebula's, reads the whole column
	 *  here. */
	get columns(): { map: Texture; origin: Vec3 } | null {
		const { sunMap, front } = this;
		if (this.plan.mode !== 'map' || !sunMap || this.sunPasses < this.plan.passes) return null;
		const home = this.origin === SUN || !front;
		this.columnMap.map = home ? sunMap.external : front.external;
		this.columnMap.origin = home ? SUN : this.origin;
		return this.columnMap;
	}

	/** Tree axes to nest axes, as rows; null until the metadata is in. */
	get frame(): NestMetadata['frame'] | null {
		return this.load.meta?.frame ?? null;
	}

	/** The nest's token; null until the metadata is in. */
	get token(): string | null {
		return this.load.meta?.token ?? null;
	}

	/** Share of the dust's effect that draws. */
	get share(): number {
		return this.enabled ? this.fade.share : 0;
	}

	/** For the gate scripts, the phone page and the dev console: a comparison with
	 *  the catalogue as it is. */
	setEnabled(on: boolean): void {
		this.enabled = on;
		this.epoch++;
		this.onChange();
	}

	/** The sources of the nest, once its data can draw. One array for the
	 *  session: this goes to a store on each frame. */
	credits(): readonly ExtrasolarCredit[] {
		const { meta } = this.load;
		if (this.load.phase !== 'ready' || !meta) return NO_CREDITS;
		this.sceneCredits ??= nestCredits(meta).filter(inSceneCredits);
		return this.sceneCredits;
	}

	private levels(meta: NestMetadata): Promise<NestLoad> {
		const { mode, nest } = this.plan;
		return Promise.all([
			this.lowLevels(meta),
			mode === 'map' && nest === 'high' ? fetchNestLevels(meta, 'high') : null
		]);
	}

	private received(cpu: readonly NestLevel[], gpu: readonly NestLevel[] | null): LoadPhase {
		if (this.plan.mode !== 'map') {
			this.settle(cpu);
			return 'ready';
		}
		this.gpu = new NestTextures(this.renderer, gpu ?? cpu);
		return 'uploading';
	}

	/** The `low` nest. Its fetch is kept, so overlapping loads and a `high`
	 *  fetch that fails do not ask for it again. A fetch that fails is dropped. */
	private lowLevels(meta: NestMetadata): Promise<readonly NestLevel[]> {
		this.cpuFetch ??= fetchNestLevels(meta, 'low').then(
			(levels) => (this.cpu = levels),
			(err: unknown) => {
				this.cpuFetch = null;
				throw err;
			}
		);
		return this.cpuFetch;
	}

	/** The CPU nest is in: the reach of the Sun. */
	private settle(cpu: readonly NestLevel[]): void {
		this.sunReach = refreshReach(nearestStructure(cpu, SUN));
		this.frontReach = this.sunReach;
	}

	private buildMaps(gpu: NestTextures, cpu: readonly NestLevel[]): void {
		const { renderer } = this;
		this.march = new DustMarch(renderer, gpu);
		this.sunMap = new SkyMap(renderer, DUST_MAP_SIZE, DUST_MAP_LAYERS);
		this.front = new SkyMap(renderer, DUST_MAP_SIZE, DUST_MAP_LAYERS);
		this.back = new SkyMap(renderer, DUST_MAP_SIZE, DUST_MAP_LAYERS);
		this.sunPasses = 0;
		this.settle(cpu);
	}

	/** A device can pass `canMarch` and still fail to link the march or to
	 *  complete a map: it goes to CPU rays for the session. */
	private noMaps(err: unknown, cpu: readonly NestLevel[]): LoadPhase {
		console.warn('[dust] no sky map on this device, one shift per node instead:', err);
		this.mapFailed = true;
		this.plan = { ...this.plan, mode: 'node' };
		this.settle(cpu);
		this.onChange();
		return 'ready';
	}

	/**
	 * Per drawn frame, before the scene draws. `camera` is in tree coordinates.
	 * `active` is true past the prefetch distance: nothing loads before it.
	 * `drawing` is true while stars draw.
	 */
	update(camera: Vec3, active: boolean, drawing: boolean, nowMs: number, dtMs: number): void {
		const { load, gpu, cpu } = this;
		if (load.phase === 'idle' && active) load.start((meta) => this.levels(meta));
		if (load.phase === 'uploading' && gpu && cpu) {
			load.upload(
				gpu,
				() => this.buildMaps(gpu, cpu),
				(err) => this.noMaps(err, cpu)
			);
		}
		const { meta } = load;
		if (load.phase !== 'ready' || !meta) return;

		if (this.marched) this.pacer.note(dtMs);
		this.marched = false;
		const at = treeToNest(meta.frame.rotation_to_icrs, camera);
		const map = this.plan.mode === 'map' && this.march !== null;
		if (map && this.bakeSun()) return;
		this.fade.step(this.enabled, dtMs);
		if (distance(at, SUN) <= this.sunReach) {
			this.goHome();
			return;
		}
		if (!drawing) {
			// No star reads a map now, and a job left open would hold the loop awake.
			this.job = null;
			this.stale = false;
			return;
		}
		if (map) this.followWithMap(at, nowMs);
		else this.followWithRays(at, nowMs);
	}

	/** One more pass of the Sun's map. True while the map is not done. */
	private bakeSun(): boolean {
		const { sunMap, march } = this;
		if (!sunMap || !march) return false;
		if (this.sunPasses >= this.plan.passes) return false;
		this.pass(march, sunMap, SUN, this.sunPasses++);
		return true;
	}

	private pass(march: DustMarch, map: SkyMap, origin: Vec3, pass: number): void {
		march.run(map, origin, passJitter(pass, this.plan.passes), 1 / (pass + 1));
		this.passes++;
		this.marched = true;
	}

	/** Within reach of the Sun its own map serves, and a job has no more use. */
	private goHome(): void {
		this.job = null;
		this.stale = false;
		if (this.origin === SUN) return;
		this.origin = SUN;
		this.frontReach = this.sunReach;
		this.epoch++;
	}

	private followWithMap(at: Vec3, nowMs: number): void {
		const { march, back, cpu } = this;
		if (!march || !back || !cpu) return;
		this.stale = distance(at, this.origin) > this.frontReach;
		let job = this.job;
		if (!job) {
			if (!this.stale || !this.pacer.due(nowMs)) return;
			job = { origin: at, reach: refreshReach(nearestStructure(cpu, at)), pass: 0 };
			this.job = job;
		}
		this.pass(march, back, job.origin, job.pass++);
		if (job.pass >= this.plan.passes || distance(at, job.origin) > job.reach) this.swap(job, nowMs);
	}

	/** The map that was being made takes over. */
	private swap(job: MapJob, nowMs: number): void {
		const finished = this.back;
		this.back = this.front;
		this.front = finished;
		this.origin = job.origin;
		this.frontReach = job.reach;
		this.job = null;
		this.stale = false;
		this.epoch++;
		this.refreshes++;
		this.pacer.refreshed(nowMs);
	}

	/** Paced like a map, so a moving camera does not start the CPU rays of all
	 *  the nodes again on each frame. */
	private followWithRays(at: Vec3, nowMs: number): void {
		const cpu = this.cpu;
		if (!cpu) return;
		this.stale = distance(at, this.origin) > this.frontReach;
		if (!this.stale || !this.pacer.due(nowMs)) return;
		this.origin = at;
		this.frontReach = refreshReach(nearestStructure(cpu, at));
		this.stale = false;
		this.marched = true;
		this.refreshes++;
		this.epoch++;
		this.pacer.refreshed(nowMs);
	}

	/** True while a frame would change what draws. */
	busy(): boolean {
		if (this.load.phase === 'uploading') return true;
		if (this.load.phase !== 'ready') return false;
		// The frame after a pass is drawn too: its length is what the pacer reads.
		if (this.fade.fading || this.marched) return true;
		if (this.plan.mode !== 'map' || !this.march) return this.stale;
		return this.sunPasses < this.plan.passes || this.job !== null || this.stale;
	}

	/** Write this frame's values into the star uniforms. */
	apply(uniforms: StarUniforms): void {
		const reading = this.plan.mode === 'map' && this.origin !== SUN && this.front !== null;
		uniforms.uDustShare.value = reading ? this.share : 0;
		const { meta } = this.load;
		if (!reading || !this.front || !this.sunMap || !meta) {
			// A plan change disposes the textures, and a bound one is a GL error.
			uniforms.uDustCam.value = null;
			uniforms.uDustSun.value = null;
			return;
		}
		uniforms.uDustCam.value = this.front.external;
		uniforms.uDustSun.value = this.sunMap.external;
		uniforms.uDustOrigin.value.set(...this.origin);
		const [a, b, c] = meta.frame.rotation_to_icrs;
		// Transpose of the rows, as Matrix3.set takes rows.
		uniforms.uDustAxes.value.set(a[0], b[0], c[0], a[1], b[1], c[1], a[2], b[2], c[2]);
	}

	/** The sample of a node, for {@link shiftOf}. Null while no CPU rays run. */
	sample(
		offsets: Float32Array,
		bounds: Uint8Array,
		centre: readonly [number, number, number]
	): NodeSample | null {
		const { cpu } = this;
		const { meta } = this.load;
		if (!cpu || !meta) return null;
		const rotation = meta.frame.rotation_to_icrs;
		return sampleNode(cpu, offsets, bounds, centre, (v) => treeToNest(rotation, v));
	}

	/** The change of column of a node from the origin in use. */
	shiftOf(sample: NodeSample): number {
		if (!this.cpu || this.origin === SUN || !this.enabled) return 0;
		return nodeShift(this.cpu, sample, this.origin);
	}

	/** The change of column of one star, at a place in tree coordinates. */
	pointShift(tree: readonly [number, number, number]): number {
		const { cpu } = this;
		const { meta } = this.load;
		if (!cpu || !meta || this.origin === SUN || !this.enabled) return 0;
		const at = treeToNest(meta.frame.rotation_to_icrs, tree);
		return columnBetween(cpu, this.origin, at) - columnBetween(cpu, SUN, at);
	}

	/** For the gates and the bench. */
	stats() {
		return {
			phase: this.load.phase,
			mode: this.plan.mode,
			nest: this.plan.nest,
			passesPerMap: this.plan.passes,
			passes: this.passes,
			refreshes: this.refreshes,
			origin: this.origin,
			reach: this.frontReach,
			share: this.share,
			stale: this.stale,
			intervalMs: this.pacer.intervalMs
		};
	}

	dispose(): void {
		this.load.dispose();
	}
}
