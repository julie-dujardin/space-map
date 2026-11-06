/**
 * The light of the stars that do not draw as points, on the sky.
 *
 * The tree draws the stars to a limit. The rest of its light is in a grid
 * (`grid.ts`). A march through that grid and the dust fills a sky map from a
 * point near the camera, and the map draws at the far plane. A map fills a
 * second texture, a few rows a frame, and then takes over. It is good while the
 * camera stays near its origin, so with nothing moving this does no work.
 *
 * Its cut is fixed and its exposure follows the map itself, never the drawn
 * limit or the nodes that load, so the glow holds still while they change.
 *
 * Model light (`model.ts`) adds the light the catalogue lacks, so the whole
 * Galaxy draws from any place. Far outside, each map has a second one about the
 * Galaxy (`outside.ts`).
 *
 * It needs the GPU nest of the dust, so the `low` tier goes without it.
 */

import { Matrix3, Matrix4, type PerspectiveCamera, type Scene, type WebGLRenderer } from 'three';
import { GpuLoad, type LoadPhase } from '$lib/scene/dust/gpu-load';
import { SkyMap, VolumeTextures, type NestTextures } from '$lib/scene/dust/march';
import { treeToNest, type Mat3Rows } from '$lib/scene/dust/nest';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import { RefreshPacer } from '$lib/scene/dust/refresh';
import { passJitter, type StarDust } from '$lib/scene/dust/star-dust';
import { BASE_LIMIT_MAG } from '$lib/scene/starfield/band';
import { SwitchFade } from '$lib/scene/visibility/switch-fade';
import { MarchBudget } from './budget';
import { GlowComposite, type GlowMapView } from './composite';
import { ADAPT_REST_MS, SUN_EXPOSURE, placeGain } from './exposure';
import { GlowEye } from './eye';
import {
	fetchGlowMetadata,
	fetchGlowVolume,
	type GlowGridTier,
	type GlowMetadata,
	type GlowVolume
} from './grid';
import type { FarDustEntry } from './far-dust';
import { GlowMarch } from './march';
import { galaxyFrame, type GalaxyFrame } from './outside';

/** How a device draws the glow. */
export interface GlowPlan {
	grid: GlowGridTier;
	/** Edge of the sky map. */
	size: number;
	/** Steps of a ray. */
	steps: number;
	/** Passes that make one map. */
	passes: number;
	/** Edge of the map about the Galaxy, for a camera far outside. */
	galaxy: number;
}

/** What the starfield knows of this frame. */
export interface GlowFrame {
	camera: PerspectiveCamera;
	/** Token of the tree that draws. */
	tree: string | null;
	/** Camera, in tree coordinates. */
	at: Vec3;
	/** Tree positions to the scene, column-major, with the scale of the tree. */
	treeToScene: readonly number[];
	treeScale: number;
	/** Past the prefetch distance: nothing loads before it. */
	active: boolean;
	/** The stars have the sky and draw. */
	drawing: boolean;
	/** Share of the sky, with the daylight gain. */
	share: number;
	nowMs: number;
	dtMs: number;
}

const FADE_MS = 800;
/** Time over which a new map takes over from the last. */
const BLEND_MS = 250;
/** The Sun, on nest axes: the reference map of the exposure is made there. */
const SUN: Vec3 = [0, 0, 0];
/**
 * The glow holds the stars fainter than this, from any place. It is the
 * skybox's limit, so the join at 2,000 AU does not move. Nothing that loads
 * moves it. The drawn limit stays fainter. Where the star budget binds
 * hardest, in the bulge, in a cluster or in flight, it is 9.1 mag or more on
 * `medium`, the smallest budget with a glow. So no light falls between the
 * two. The stars between them count twice, as a dot and in the glow.
 */
export const GLOW_CUT_MAG = BASE_LIMIT_MAG;

const distance = (a: Vec3, b: Vec3): number => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

/** The model's share of a map's light over which the label shows, and under
 *  which it goes again: two, so a share near one does not flicker. */
export const MODEL_SHOWN_SHARE = 0.25;
export const MODEL_HIDDEN_SHARE = 0.2;

/** A map being made. */
interface MapJob {
	origin: Vec3;
	reach: number;
	pass: number;
	row: number;
	/** In each pass, the sky map first, then the map about the Galaxy. */
	galaxyStage: boolean;
	frame: GalaxyFrame | null;
	/** The map at the Sun, whose mean is the exposure's reference. */
	reference: boolean;
}

/** A sky map, the map about the Galaxy beside it, and that map's frame. */
class MapSet {
	frame: GalaxyFrame | null = null;
	private readonly view: GlowMapView;

	constructor(
		readonly sky: SkyMap,
		readonly galaxy: SkyMap | null
	) {
		this.view = { sky: sky.external, galaxy: null, frame: null };
	}

	/** What the composite reads. */
	get shown(): GlowMapView {
		this.view.galaxy = this.frame && this.galaxy ? this.galaxy.external : null;
		this.view.frame = this.frame;
		return this.view;
	}

	dispose(): void {
		this.sky.dispose();
		this.galaxy?.dispose();
	}
}

export class GlowSky {
	private enabled = true;
	private plan: GlowPlan | null;
	private readonly load: GpuLoad<GlowMetadata, GlowVolume>;
	private grid: VolumeTextures | null = null;
	private model: VolumeTextures | null = null;
	private far: { textures: VolumeTextures; entry: FarDustEntry } | null = null;
	/** The dust's nest that the march reads. */
	private nest: NestTextures | null = null;
	private march: GlowMarch | null = null;
	/** The maps that draw, the ones they blend in from, and the ones being made. */
	private front: MapSet | null = null;
	private previous: MapSet | null = null;
	private back: MapSet | null = null;
	/** The model holds a visible share of the front map's light. */
	private modelShown = false;
	/** That, and the glow shows. */
	private modelSeen = false;
	/** Progress of the blend from the previous map, 0 to 1. */
	private blend = 1;
	private composite: GlowComposite | null = null;
	private eye: GlowEye | null = null;
	private budget = new MarchBudget(1);
	private job: MapJob | null = null;
	/** Where the front map was made. Null before the first. */
	private origin: Vec3 | null = null;
	private reach = 0;
	private stale = false;
	private marched = false;
	private referenceStarted = false;
	/** The eye has the mean of the map at the Sun, and of the front map. */
	private sunMeasured = false;
	private frontMeasured = false;
	/** A mean came in that the eye has not started on. */
	private eyeDue = false;
	private eyeStarted = false;
	/** The eye adapts until then, at the most. */
	private eyeRestMs = 0;
	/** Gain over the eye's from the camera's place, this frame. */
	private placeGain = 1;
	private lastMs = 0;
	private readonly pacer = new RefreshPacer();
	private fade = new SwitchFade(false, FADE_MS);
	private readonly sceneToTree = new Matrix4();
	/** The grid's inputs were checked against what draws, once a session. */
	private inputsChecked = false;
	private rowsMarched = 0;
	private passes = 0;
	private refreshes = 0;

	constructor(
		private readonly renderer: WebGLRenderer,
		private readonly scene: Scene,
		plan: GlowPlan | null,
		private readonly dust: StarDust,
		private readonly onChange: () => void
	) {
		this.plan = plan;
		this.load = new GpuLoad(
			renderer,
			'glow',
			'the grid',
			{
				metadata: fetchGlowMetadata,
				received: (_meta, volume) => this.received(volume),
				release: (live) => this.release(live),
				reset: () => this.reset()
			},
			onChange
		);
	}

	/** The tier changed. On the same grid tier the grid stays, and only what is
	 *  built on it is made again. */
	setPlan(plan: GlowPlan | null): void {
		const old = this.plan;
		this.plan = plan;
		const shape =
			plan?.size === old?.size &&
			plan?.steps === old?.steps &&
			plan?.passes === old?.passes &&
			plan?.galaxy === old?.galaxy;
		if (plan?.grid === old?.grid && shape) return;
		if (plan?.grid !== old?.grid || this.renderer.getContext().isContextLost()) {
			this.load.restart(true);
		} else if (this.load.phase === 'ready') {
			this.rebuild();
		}
	}

	/** No map and no means, for a load or a build that starts again. */
	private reset(): void {
		this.job = null;
		this.stale = false;
		this.marched = false;
		this.origin = null;
		this.referenceStarted = this.sunMeasured = this.frontMeasured = false;
		this.eyeDue = this.eyeStarted = false;
		this.eyeRestMs = 0;
		this.modelShown = false;
	}

	/** Free the GPU objects. A lost context took them already. */
	private release(live: boolean): void {
		this.releaseMaps(live);
		if (live) {
			this.grid?.dispose();
			this.model?.dispose();
			this.far?.textures.dispose();
		}
		this.grid = this.model = null;
		this.far = null;
	}

	/** Free what the build made on the grid. */
	private releaseMaps(live: boolean): void {
		if (live) {
			this.front?.dispose();
			this.previous?.dispose();
			this.back?.dispose();
			this.march?.dispose();
			this.eye?.dispose();
		}
		this.composite?.dispose();
		this.front = this.previous = this.back = null;
		this.march = this.nest = this.composite = this.eye = null;
	}

	/** Build the march, the maps, the eye and the composite again on the grid as
	 *  it is. The grid does not depend on the dust's nest or on a map's size,
	 *  steps and passes. */
	private rebuild(): void {
		this.releaseMaps(true);
		this.reset();
		this.load.phase = 'uploading';
		this.onChange();
	}

	/** For the gate scripts and the phone page: a comparison with no glow, from
	 *  the next frame. */
	setEnabled(on: boolean): void {
		this.enabled = on;
		this.fade = new SwitchFade(on && this.fade.share > 0, FADE_MS);
		this.onChange();
	}

	/** A throw here makes the load try again. So the fields change only once
	 *  every texture is made, and a throw frees what it made. */
	private received(volume: GlowVolume): LoadPhase {
		const { size, shells } = volume.entry;
		const { model, far } = volume;
		const made: { dispose(): void }[] = [];
		const keep = <T extends { dispose(): void }>(textures: T): T => {
			made.push(textures);
			return textures;
		};
		try {
			const grid = keep(
				new VolumeTextures(
					this.renderer,
					[volume.a, volume.b].map((data) => ({ size: [size, size, shells], data })),
					'rgba16f'
				)
			);
			const boxes = model
				? keep(new VolumeTextures(this.renderer, [model.inner, model.outer], 'r16f'))
				: null;
			const farDust = far
				? {
						textures: keep(
							new VolumeTextures(this.renderer, [{ size: far.size, data: far.codes }], 'r8')
						),
						entry: far.entry
					}
				: null;
			this.grid = grid;
			this.model = boxes;
			this.far = farDust;
		} catch (err) {
			for (const textures of made) textures.dispose();
			throw err;
		}
		return 'uploading';
	}

	/** The grid, then the model and the far dust, a few slices a frame. */
	private uploads(volumes: (VolumeTextures | null | undefined)[]) {
		const all = volumes.filter((v): v is VolumeTextures => !!v);
		return {
			get uploaded() {
				return all.every((v) => v.uploaded);
			},
			step() {
				all.find((v) => !v.uploaded)?.step();
			}
		};
	}

	private build(
		nest: NestTextures,
		grid: VolumeTextures,
		plan: GlowPlan,
		meta: GlowMetadata,
		rotation: Mat3Rows
	): void {
		const { renderer, scene } = this;
		// The map about the Galaxy draws model light, so a grid alone has none.
		const galaxy = meta.model ? plan.galaxy : 0;
		this.march = new GlowMarch(
			renderer,
			nest,
			grid,
			this.model,
			this.far,
			meta,
			meta.tiers[plan.grid],
			{ ...plan, galaxy }
		);
		const set = () => {
			const sky = new SkyMap(renderer, plan.size);
			try {
				return new MapSet(sky, galaxy > 0 ? new SkyMap(renderer, galaxy) : null);
			} catch (err) {
				sky.dispose();
				throw err;
			}
		};
		this.front = set();
		this.previous = set();
		this.back = set();
		this.eye = new GlowEye(renderer, plan.size);
		const [a, b, c] = rotation;
		const axes = new Matrix3().set(a[0], b[0], c[0], a[1], b[1], c[1], a[2], b[2], c[2]);
		this.composite = new GlowComposite(scene, plan.size, axes);
		this.budget = new MarchBudget(plan.size);
		this.nest = nest;
	}

	/** The export made the grid from a tree and a nest. Others still draw: a
	 *  Milky Way a little stale is better than none. */
	private checkInputs(meta: GlowMetadata, tree: string | null): void {
		if (this.inputsChecked) return;
		this.inputsChecked = true;
		const { inputs } = meta;
		const nest = this.dust.token;
		if (inputs.tree === tree && inputs.dust === nest) return;
		console.warn(
			`[glow] the grid is of tree ${inputs.tree} and nest ${inputs.dust}; this page draws tree ${tree} and nest ${nest}`
		);
	}

	/** Per drawn frame, after the dust has updated. */
	update(frame: GlowFrame): void {
		this.lastMs = frame.nowMs;
		const { load, plan, grid } = this;
		const nest = this.dust.marchNest;
		if (this.nest && this.nest !== nest) this.rebuild();
		if (load.phase === 'idle' && frame.active && plan && nest) {
			load.start((meta) => fetchGlowVolume(meta, plan.grid));
		}
		const { meta } = load;
		const rotation = this.dust.frame?.rotation_to_icrs;
		if (load.phase === 'uploading' && grid && nest && plan && meta && rotation) {
			this.checkInputs(meta, frame.tree);
			load.upload(
				this.uploads([grid, this.model, this.far?.textures]),
				() => this.build(nest, grid, plan, meta, rotation),
				(err) => {
					// A throw here would repeat on every frame.
					console.warn('[glow] no sky map on this device:', err);
					return 'none';
				}
			);
		}
		if (load.phase !== 'ready') return;

		// The frame after a march sets the budget and the pace of refreshes.
		if (this.marched) {
			this.budget.note(frame.dtMs);
			this.pacer.note(frame.dtMs);
		}
		this.marched = false;
		if (!rotation) return;
		const at = treeToNest(rotation, frame.at);
		const wanted = this.enabled && (frame.drawing || this.origin === null);
		if (wanted) this.follow(at, frame.nowMs, meta?.model?.centre_pc ?? null);
		else this.drop();
		this.draw(frame, at);
	}

	/** No map is made while the glow is off or the stars do not draw. The map at
	 *  the Sun starts again from its first row when it is wanted again. */
	private drop(): void {
		if (this.job?.reference) this.referenceStarted = false;
		this.job = null;
		this.stale = false;
	}

	private follow(at: Vec3, nowMs: number, centre: Vec3 | null): void {
		const { march, back, plan } = this;
		if (!march || !back || !plan) return;
		this.stale = this.origin === null || distance(at, this.origin) > this.reach;
		let job = this.job;
		if (!job) {
			const reference = !this.referenceStarted;
			if (!reference && (!this.stale || !this.pacer.due(nowMs))) return;
			const origin = reference ? SUN : at;
			job = {
				origin,
				// The dust found this reach for its own refresh, near the same place.
				reach: reference ? this.dust.reachAtSun : this.dust.latestReach,
				pass: 0,
				row: 0,
				galaxyStage: false,
				frame: back.galaxy && centre ? galaxyFrame(origin, centre) : null,
				reference
			};
			this.referenceStarted ||= reference;
			this.job = job;
		}
		// The budget counts rows of the sky map; a row of the other map costs more.
		let texels = this.budget.rows * plan.size;
		this.marched = texels > 0 && job.pass < plan.passes;
		while (texels > 0 && job.pass < plan.passes) {
			const galaxy = job.galaxyStage ? back.galaxy : null;
			const map = galaxy ?? back.sky;
			const edge = galaxy ? plan.galaxy : plan.size;
			const count = Math.min(Math.max(Math.floor(texels / edge), 1), edge - job.row);
			march.run(
				map,
				job.origin,
				GLOW_CUT_MAG,
				passJitter(job.pass, plan.passes),
				1 / (job.pass + 1),
				job.row,
				count,
				galaxy ? job.frame : null
			);
			job.row += count;
			texels -= count * edge;
			this.rowsMarched += count;
			if (job.row < edge) continue;
			job.row = 0;
			if (!job.galaxyStage && job.frame && back.galaxy) {
				job.galaxyStage = true;
				continue;
			}
			job.galaxyStage = false;
			job.pass++;
			this.passes++;
		}
		const near = distance(at, job.origin) <= job.reach;
		if (job.reference) {
			if (job.pass < plan.passes) return;
			this.measure(back.sky, true);
			// The map at the Sun is the first map too while the camera is near it.
			if (near) this.swap(job, nowMs);
			else this.job = null;
			return;
		}
		const done =
			job.pass >= plan.passes || (job.pass > 0 && job.row === 0 && !job.galaxyStage && !near);
		// A map that took over during a blend would drop the map it blends from at
		// once. So it waits, and marches more passes meanwhile.
		if (done && this.blend >= 1) this.swap(job, nowMs);
	}

	private measure(map: SkyMap, reference: boolean): void {
		this.eye?.measure(map, reference);
		if (reference) this.sunMeasured = true;
		else this.frontMeasured = true;
		// The eye needs both means. One alone would hold the frame loop awake.
		this.eyeDue = this.sunMeasured && this.frontMeasured;
	}

	/** The map that was being made takes over, blended in so a refresh shows no
	 *  step. The first map needs no blend: the fade brings it in. */
	private swap(job: MapJob, nowMs: number): void {
		if (this.back) {
			this.back.frame = job.frame;
			this.measure(this.back.sky, false);
			this.eye?.askShare(this.modelShown ? MODEL_HIDDEN_SHARE : MODEL_SHOWN_SHARE);
		}
		const free = this.previous;
		this.previous = this.front;
		this.front = this.back;
		this.back = free;
		this.blend = this.origin === null ? 1 : 0;
		this.origin = job.origin;
		this.reach = job.reach;
		this.job = null;
		this.stale = false;
		this.refreshes++;
		this.pacer.refreshed(nowMs);
	}

	/** Nothing shows before the eye has both means. `at` is the camera on nest axes. */
	private draw(frame: GlowFrame, at: Vec3): void {
		const { composite, front, previous, eye } = this;
		if (!composite || !front || !previous || !eye) return;
		this.placeGain = placeGain(at, this.load.meta?.model?.centre_pc ?? null);
		const shown = eye.shareAnswer();
		if (shown !== null) this.modelShown = shown;
		const known = this.sunMeasured && this.frontMeasured;
		this.fade.step(this.enabled && known && frame.drawing, frame.dtMs);
		this.blend = Math.min(this.blend + frame.dtMs / BLEND_MS, 1);
		const share = this.fade.share * frame.share;
		if (known) this.adapt(eye, share > 0, frame.nowMs, frame.dtMs);
		this.modelSeen = this.modelShown && share > 0 && this.eyeStarted;
		if (share <= 0 || !this.eyeStarted) {
			composite.hide();
			return;
		}
		const e = frame.treeToScene;
		const k = 1 / frame.treeScale;
		// The rotation only: the transpose of tree to scene.
		this.sceneToTree.set(
			e[0] * k,
			e[1] * k,
			e[2] * k,
			0,
			e[4] * k,
			e[5] * k,
			e[6] * k,
			0,
			e[8] * k,
			e[9] * k,
			e[10] * k,
			0,
			0,
			0,
			0,
			1
		);
		composite.show(
			front.shown,
			previous.shown,
			this.blend,
			eye.texture,
			SUN_EXPOSURE * this.placeGain,
			share,
			frame.camera,
			this.sceneToTree
		);
	}

	/** The eye eases to a new mean while the glow shows, and takes it at once
	 *  while it does not. It stops and takes its target when the GPU finds it
	 *  close, or at the end of the time of rest, so the frame loop can rest. */
	private adapt(eye: GlowEye, seen: boolean, nowMs: number, dtMs: number): void {
		const close = eye.answer();
		if (!seen || !this.eyeStarted) {
			if (this.eyeDue || this.eyeRestMs > 0 || !this.eyeStarted) eye.step(0, true);
			this.eyeStarted = true;
			this.eyeDue = false;
			this.eyeRestMs = 0;
			return;
		}
		if (this.eyeDue) this.eyeRestMs = nowMs + ADAPT_REST_MS;
		else if (this.eyeRestMs === 0) return;
		else if (close || nowMs >= this.eyeRestMs) {
			eye.step(0, true);
			this.eyeRestMs = 0;
			return;
		}
		this.eyeDue = false;
		eye.step(dtMs, false);
		eye.ask();
	}

	/** Model light holds a visible share of the glow that shows, so the UI must
	 *  say the view is model. */
	get modelInView(): boolean {
		return this.load.phase === 'ready' && this.modelSeen;
	}

	/** True while a frame would change what draws. */
	busy(): boolean {
		if (this.load.phase === 'uploading') return this.dust.marchNest !== null;
		if (this.load.phase !== 'ready') return false;
		// The frame after a march is drawn too: its length sets the budget.
		if (this.fade.fading || this.marched || this.blend < 1) return true;
		if (this.eyeDue || this.eyeRestMs > 0) return true;
		// The label waits for the answer on the model's share.
		if (this.eye?.sharePending) return true;
		return this.job !== null || this.stale;
	}

	/** For the gates and the bench. */
	stats() {
		return {
			phase: this.load.phase,
			plan: this.plan,
			passes: this.passes,
			rows: this.rowsMarched,
			refreshes: this.refreshes,
			origin: this.origin,
			reach: this.reach,
			cut: GLOW_CUT_MAG,
			adaptingMs: Math.max(this.eyeRestMs - this.lastMs, 0),
			model: this.load.meta?.model ? true : false,
			modelInView: this.modelInView,
			galaxy: this.front?.frame
				? { tan: this.front.frame.tan, share: this.front.frame.share }
				: null,
			placeGain: this.placeGain,
			share: this.fade.share,
			stale: this.stale,
			busy: this.busy(),
			budgetRows: this.budget.rows
		};
	}

	/** For the gates: the eye's gain over the Sun's exposure, its target and the
	 *  two means. It waits for the GPU. */
	probe() {
		return this.eye?.read() ?? null;
	}

	dispose(): void {
		this.load.dispose();
	}
}
