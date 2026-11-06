/**
 * The light of the stars that do not draw as points, on the sky.
 *
 * The tree draws the stars to a limit. The rest of its light is in a grid
 * (`grid.ts`). Each frame that the camera moves, a march through that grid and
 * the dust draws the view from the camera into a target at a part of the
 * screen's resolution, and the composite scales it up. So the glow is a
 * function of the camera's pose alone, and it shows the pose of the frame it
 * draws in. At rest a few more passes, each with another fixed jitter and
 * another fixed place in the texel, blend in, and then it does no work.
 *
 * Its cut and its exposure are fixed by the camera's place, never by the drawn
 * limit, the nodes that load or the sky, so the glow holds still while they
 * change.
 *
 * Model light (`model.ts`) adds the light the catalogue lacks, so the whole
 * Galaxy draws from any place.
 *
 * Light that is not starlight (`emission.ts`) is in the march. Inside the solar
 * system the skybox is the sky, and it holds none of it, so a map of the
 * emission alone from the Sun draws over the skybox, and the far H II regions
 * (`regions.ts`) draw from the camera on both sides of the join. So the join
 * does not step by them.
 *
 * Past the join the sky from the Sun shares the glow with the march, by the
 * camera's distance from the Sun (`joinShare`): the sky without its bright
 * stars (`starless.ts`), blurred past the parallax of the stars near the join,
 * and the emission map. So the sky does not step where the march and the
 * skybox differ, and the dots alone draw the bright stars. Until that sky
 * loads, and where the export has none, the skybox stands in for it, blurred
 * past the size of its stars.
 *
 * A device too slow for its plan while the camera moves steps down at most
 * twice a session (`stepDown`).
 *
 * It needs the GPU nest of the dust, so the `low` tier goes without it.
 */

import {
	Euler,
	Matrix3,
	Matrix4,
	Vector2,
	Vector4,
	type CubeTexture,
	type PerspectiveCamera,
	type Scene,
	type WebGLRenderer
} from 'three';
import { GpuLoad, type LoadPhase } from '$lib/scene/dust/gpu-load';
import { FloatTarget, SkyMap, VolumeTextures, type NestTextures } from '$lib/scene/dust/march';
import { treeToNest, type Mat3Rows } from '$lib/scene/dust/nest';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import { passJitter, type StarDust } from '$lib/scene/dust/star-dust';
import { GLOW_CUT_MAG } from '$lib/scene/starfield/band';
import { SwitchFade } from '$lib/scene/visibility/switch-fade';
import { GlowComposite, ViewRays } from './composite';
import { SUN_EXPOSURE, joinShare, placeGain } from './exposure';
import type { StarlessSky } from './starless';
import { ALL_PARTS, EmissionTextures, type EmissionParts, type EmissionRegions } from './emission';
import {
	fetchGlowMetadata,
	fetchGlowVolume,
	type GlowGridTier,
	type GlowMetadata,
	type GlowVolume
} from './grid';
import type { CloudBox } from './clouds';
import type { FarDustEntry } from './far-dust';
import type { CoarseLayout } from './prefilter';
import { GlowMarch, subTexel, type MarchView } from './march';
import { GlowRegions } from './regions';

/** How a device draws the glow. */
export interface GlowPlan {
	grid: GlowGridTier;
	/** The screen target is the view in CSS pixels over this, on each side. */
	divisor: number;
	/** Steps of a ray's first span. */
	steps: number;
	/** Passes that blend in at rest. */
	passes: number;
	/** Edge of the map of the emission alone at the Sun. */
	sunSize: number;
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
	/** The stars can draw: their layer is on and the tree is in. Not their
	 *  share of the sky: `share` fades the glow with them, and a second fade
	 *  on top would dim the sky as the stars take it from the skybox. */
	drawing: boolean;
	/** Share of the sky, with the daylight gain. */
	share: number;
	/** Share of the sky that the skybox holds, with the daylight gain. */
	skybox: number;
	/** Height of the view in CSS pixels. */
	heightPx: number;
	/** The skybox's layer is on. */
	skyboxLayer: boolean;
	nowMs: number;
	dtMs: number;
}

const FADE_MS = 800;
/** The Sun, on nest axes: the map of the emission alone is made there. */
const SUN: Vec3 = [0, 0, 0];
/** Steps of the map at the Sun on every tier, so the join holds on each. */
const SUN_STEPS = 48;
/** Texels on a face of the sky's cube as the glow reads it: 0.35 degrees
 *  each, wider than the parallax of the bright stars near the join. */
const SKYBOX_FACE_TEXELS = 256;
/** Share of the march past which the label says the view is model: the model
 *  holds 0.321 of the glow's light at the Sun, and the label needs 0.25. */
const LABEL_JOIN_SHARE = 0.25 / 0.321;

/** The skybox as the glow reads it past the join. */
export interface SkyboxSource {
	texture: CubeTexture;
	/** `scene.backgroundRotation`. */
	rotation: Euler;
	/** Texels on a face of the cube's first level. */
	faceTexels: number;
}

const _euler = new Euler();
const _matrix = new Matrix4();
const _camera = new Matrix3();
/** Three's cube background flips x (`flipEnvMap`). */
const FLIP_X = new Matrix3().set(-1, 0, 0, 0, 1, 0, 0, 0, 1);

/** The pose a screen target was marched for: the camera on nest axes, the view
 *  to nest axes and the lens. */
const POSE_LENGTH = 3 + 9 + 4;
/**
 * A move of the camera under this share of the finest cell of the dust is no
 * new pose. The march cannot show it, and with the focus on a body the camera
 * moves with time: it would start again at pass 0 in each frame.
 */
const POSE_SHIFT_CELLS = 1e-4;

/** The median frame (ms) after a march of a new pose over which a device is
 *  too slow for its plan. */
const SLOW_FRAME_MS = 25;
/** Frames after a march of a new pose that one step of the plan is judged on. */
const JUDGED_FRAMES = 30;
/** Steps down from a tier's plan: a coarser target, then fewer steps too. */
const LAST_RUNG = 2;

/**
 * The plan on a device that was too slow for it `rung` times. Each step cuts
 * the cost of a moving frame's march by about half or more. A step is never
 * taken back in a session, so a flight never goes back and forth between two
 * pictures of one pose.
 */
export function stepDown(plan: GlowPlan, rung: number): GlowPlan {
	if (rung <= 0) return plan;
	return {
		...plan,
		divisor: plan.divisor * 2,
		steps: rung >= 2 ? Math.max(Math.round(plan.steps / 2), 8) : plan.steps
	};
}

export class GlowSky {
	private enabled = true;
	/** The tier's plan, and the plan that draws: the tier's, stepped down on a
	 *  slow device. */
	private tierPlan: GlowPlan | null;
	private plan: GlowPlan | null;
	/** Steps down from the tier's plan, and the frames that judge the next. */
	private rung = 0;
	private readonly judged = new Float64Array(JUDGED_FRAMES);
	private judgedCount = 0;
	private judging = true;
	/** The last frame marched a new pose: this frame's length is its cost. */
	private marchedPose = false;
	private readonly load: GpuLoad<GlowMetadata, GlowVolume>;
	private grid: VolumeTextures | null = null;
	private model: VolumeTextures | null = null;
	private emission: EmissionTextures | null = null;
	private regionRows: EmissionRegions | null = null;
	/** Boxes of the Magellanic Clouds, where the march takes steps of its own. */
	private clouds: CloudBox[] = [];
	/** The coarse copies of the grid, the last two textures of `grid`. */
	private coarse: CoarseLayout | null = null;
	private coarseReads = true;
	/** The parts of the emission that draw: all of them, but in the gates. */
	private parts: EmissionParts = ALL_PARTS;
	/** The emission alone from the Sun, over the skybox, and its passes. */
	private sunEmission: SkyMap | null = null;
	private sunPass = 0;
	private inside: GlowComposite | null = null;
	private regions: GlowRegions | null = null;
	private insideFade = new SwitchFade(false, FADE_MS);
	private far: { textures: VolumeTextures; entry: FarDustEntry } | null = null;
	/** The dust's nest that the march reads. */
	private nest: NestTextures | null = null;
	private march: GlowMarch | null = null;
	/** This frame's rays from the camera, and the target they fill. */
	private rays: ViewRays | null = null;
	private view: MarchView | null = null;
	private readonly lens: [number, number, number, number] = [0, 0, 0, 0];
	private readonly offset: [number, number] = [0, 0];
	private screen: FloatTarget | null = null;
	/** The pose of the screen target, and its passes. No pose: it holds none. */
	private readonly pose = new Float64Array(POSE_LENGTH);
	/** The place the pose was marched from, on nest axes. */
	private readonly origin: Vec3 = [0, 0, 0];
	/** Least move (pc) of the camera that is a new pose. */
	private poseShift = 0;
	private posed = false;
	private pass = 0;
	/** The march from the camera shows this frame. */
	private marching = false;
	private composite: GlowComposite | null = null;
	/** The sky from the Sun past the join, and its rays: view to the cube's axes. */
	private cube: GlowComposite | null = null;
	private cubeShown = false;
	private readonly cubeRays = { axes: new Matrix3(), lens: new Vector4() };
	/** Gain by the camera's place, this frame. */
	private placeGain = 1;
	private fade = new SwitchFade(false, FADE_MS);
	private readonly sceneToTree = new Matrix4();
	private readonly buffer = new Vector2();
	/** The camera on nest axes, this frame. */
	private at: Vec3 = [0, 0, 0];
	/** The grid's inputs were checked against what draws, once a session. */
	private inputsChecked = false;
	private passesMarched = 0;
	/** For the gates: the passes at rest stop after this many. */
	private passLimit = Infinity;
	private poses = 0;

	constructor(
		private readonly renderer: WebGLRenderer,
		private readonly scene: Scene,
		plan: GlowPlan | null,
		private readonly dust: StarDust,
		private readonly onChange: () => void,
		private readonly skybox: () => SkyboxSource | null = () => null,
		private readonly starless: StarlessSky | null = null
	) {
		this.tierPlan = this.plan = plan;
		this.load = new GpuLoad(
			renderer,
			'glow',
			'the grid',
			{
				metadata: fetchGlowMetadata,
				received: (meta, volume) => this.received(meta, volume),
				release: (live) => this.release(live),
				reset: () => this.reset()
			},
			onChange
		);
	}

	/** The tier changed. A slow device keeps its steps down. */
	setPlan(plan: GlowPlan | null): void {
		this.tierPlan = plan;
		this.usePlan(plan && stepDown(plan, this.rung));
	}

	/** On the same grid tier the grid stays, and only what is built on it is made
	 *  again. A new divisor needs only a new target, which the next march makes. */
	private usePlan(plan: GlowPlan | null): void {
		const old = this.plan;
		this.plan = plan;
		const built =
			plan?.steps === old?.steps && plan?.passes === old?.passes && plan?.sunSize === old?.sunSize;
		if (plan?.grid === old?.grid && built) return;
		if (plan?.grid !== old?.grid || this.renderer.getContext().isContextLost()) {
			this.load.restart(true);
		} else if (this.load.phase === 'ready') {
			this.rebuild();
		}
	}

	/** No target holds a pose, for a load or a build that starts again. */
	private reset(): void {
		this.posed = false;
		this.pass = 0;
		this.sunPass = 0;
	}

	/** Free the GPU objects. A lost context took them already. */
	private release(live: boolean): void {
		this.releaseBuild(live);
		if (live) {
			this.grid?.dispose();
			this.model?.dispose();
			this.far?.textures.dispose();
			this.emission?.dispose();
		}
		this.grid = this.model = null;
		this.far = null;
		this.emission = null;
		this.regionRows = null;
		this.clouds = [];
		this.coarse = null;
	}

	/** Free what the build made on the grid. */
	private releaseBuild(live: boolean): void {
		if (live) {
			this.screen?.dispose();
			this.march?.dispose();
			this.sunEmission?.dispose();
		}
		this.composite?.dispose();
		this.cube?.dispose();
		this.cubeShown = false;
		this.inside?.dispose();
		this.regions?.dispose();
		this.screen = null;
		this.march = this.nest = this.composite = this.cube = this.rays = this.view = null;
		this.sunEmission = this.inside = this.regions = null;
	}

	/** Build the march, the targets and the composites again on the grid as it
	 *  is. The grid does not depend on the dust's nest or on the plan's shape. */
	private rebuild(): void {
		this.releaseBuild(true);
		this.reset();
		this.load.phase = 'uploading';
		this.onChange();
	}

	/** For the gate scripts and the phone page: a comparison with no glow, from
	 *  the next frame. */
	setEnabled(on: boolean): void {
		this.enabled = on;
		this.fade = new SwitchFade(on && this.fade.share > 0, FADE_MS);
		this.insideFade = new SwitchFade(on && this.insideFade.share > 0, FADE_MS);
		this.onChange();
	}

	/** Debug menu: off, the march reads the grid itself at every width, as
	 *  it did before the coarse copies. The pose is marched again. */
	setCoarseReads(on: boolean): void {
		if (on === this.coarseReads) return;
		this.coarseReads = on;
		if (this.march) this.march.coarseReads = on;
		this.reset();
		this.onChange();
	}

	/** For the gate scripts: march no more than `passes` passes of a pose, so
	 *  pass 0 alone can be read at rest. The pose is marched again. */
	limitPasses(passes: number): void {
		this.passLimit = passes;
		this.posed = false;
		this.onChange();
	}

	/** For the gate scripts: the parts of the emission that draw. The march is
	 *  built again on the grid as it is. With none, the glow draws as on a host
	 *  with no emission. */
	setEmission(parts: EmissionParts): void {
		this.parts = { ...parts };
		if (this.load.phase === 'ready') this.rebuild();
		else this.onChange();
	}

	/** A throw here makes the load try again. So the fields change only once
	 *  every texture is made, and a throw frees what it made. */
	private received(meta: GlowMetadata, volume: GlowVolume): LoadPhase {
		const { size, shells } = volume.entry;
		const { model, far, emission, coarse } = volume;
		const made: { dispose(): void }[] = [];
		const keep = <T extends { dispose(): void }>(textures: T): T => {
			made.push(textures);
			return textures;
		};
		try {
			const textures = [volume.a, volume.b].map((data) => ({
				size: [size, size, shells] as Vec3,
				data
			}));
			if (coarse) {
				const { width, height } = coarse.layout;
				for (const data of [coarse.a, coarse.b])
					textures.push({ size: [width, height, shells], data });
			}
			const grid = keep(new VolumeTextures(this.renderer, textures, 'rgba16f'));
			const lines =
				emission && meta.emission
					? keep(new EmissionTextures(this.renderer, emission, meta.emission))
					: null;
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
			this.emission = lines;
			this.regionRows = emission?.regions ?? null;
			this.clouds = volume.clouds;
			this.coarse = coarse?.layout ?? null;
			this.model = boxes;
			this.far = farDust;
		} catch (err) {
			for (const textures of made) textures.dispose();
			throw err;
		}
		return 'uploading';
	}

	/** The grid, then the model, the far dust and the emission, a few slices a frame. */
	private uploads(volumes: (VolumeTextures | EmissionTextures | null | undefined)[]) {
		const all = volumes.filter((v): v is VolumeTextures | EmissionTextures => !!v);
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
		const { renderer, scene, emission, parts } = this;
		this.march = new GlowMarch(
			renderer,
			nest,
			grid,
			this.model,
			this.far,
			meta,
			meta.tiers[plan.grid],
			{ screen: plan.steps, sky: SUN_STEPS },
			plan.sunSize,
			plan.grid,
			emission && meta.emission ? { meta: meta.emission, textures: emission, parts } : null,
			this.clouds,
			this.coarse
		);
		this.march.coarseReads = this.coarseReads;
		const [a, b, c] = rotation;
		const axes = new Matrix3().set(a[0], b[0], c[0], a[1], b[1], c[1], a[2], b[2], c[2]);
		this.rays = new ViewRays(axes);
		this.view = { axes: this.rays.axes.elements, lens: this.lens, offset: this.offset };
		this.composite = new GlowComposite(scene, { kind: 'screen' }, this.rays);
		this.cubeRays.lens = this.rays.lens;
		this.cube = new GlowComposite(scene, { kind: 'cube' }, this.cubeRays);
		if (this.march.emissionAlone) {
			this.sunEmission = new SkyMap(renderer, plan.sunSize);
			this.inside = new GlowComposite(scene, { kind: 'sky', size: plan.sunSize }, this.rays);
		}
		if (meta.emission && this.regionRows && parts.regions) {
			this.regions = new GlowRegions(scene, this.regionRows, meta.emission, this.rays);
		}
		const cells = nest.levels.flatMap(({ half, size }) => half.map((h, i) => (2 * h) / size[i]));
		this.poseShift = POSE_SHIFT_CELLS * Math.min(...cells);
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

	/** Per drawn frame, after the dust has updated and the camera has its pose. */
	update(frame: GlowFrame): void {
		if (this.marchedPose) this.judge(frame.dtMs);
		this.marchedPose = false;
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
				this.uploads([grid, this.model, this.far?.textures, this.emission]),
				() => this.build(nest, grid, plan, meta, rotation),
				noGlow
			);
		}
		if (load.phase !== 'ready' || !rotation || !plan) return;
		this.at = treeToNest(rotation, frame.at);
		this.placeGain = placeGain(this.at, meta?.model?.centre_pc ?? null);
		this.setSceneToTree(frame);
		this.rays?.set(frame.camera, this.sceneToTree);
		if (this.enabled) this.marchSun(plan);
		this.fade.step(this.enabled && frame.drawing, frame.dtMs);
		const share = this.fade.share * frame.share;
		this.marching = share * joinShare(Math.hypot(...this.at)) > 0;
		if (this.marching) this.marchScreen(plan);
		this.draw(frame, share);
	}

	/** The rotation only: the transpose of tree to scene. */
	private setSceneToTree(frame: GlowFrame): void {
		const e = frame.treeToScene;
		const k = 1 / frame.treeScale;
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
	}

	/** One pass a frame of the map of the emission alone at the Sun, once. */
	private marchSun(plan: GlowPlan): void {
		const { march, sunEmission } = this;
		if (!march || !sunEmission || this.sunPass >= plan.passes) return;
		const pass = this.sunPass++;
		march.run(sunEmission, SUN, GLOW_CUT_MAG, passJitter(pass, plan.passes), 1 / (pass + 1), null);
	}

	/**
	 * March this frame's pose into the screen target. A new pose starts again
	 * from the first pass; the same pose blends in the next, until the last.
	 * The target is sized from CSS pixels, so its cost does not grow with the
	 * pixel ratio.
	 */
	private marchScreen(plan: GlowPlan): void {
		const { march, rays, view } = this;
		if (!march || !rays || !view) return;
		const size = this.renderer.getSize(this.buffer);
		const width = Math.max(Math.ceil(size.x / plan.divisor), 1);
		const height = Math.max(Math.ceil(size.y / plan.divisor), 1);
		if (this.screen?.width !== width || this.screen.height !== height) {
			this.screen?.dispose();
			this.screen = null;
			this.posed = false;
			try {
				this.screen = new FloatTarget(this.renderer, width, height);
			} catch (err) {
				this.load.fail(err, noGlow);
				return;
			}
		}
		if (!this.samePose(rays)) this.pass = 0;
		if (this.pass >= Math.min(plan.passes, this.passLimit)) return;
		const pass = this.pass++;
		rays.lens.toArray(this.lens);
		subTexel(pass, plan.passes, this.offset);
		const jitter = passJitter(pass, plan.passes);
		march.run(this.screen, this.origin, GLOW_CUT_MAG, jitter, 1 / (pass + 1), view);
		this.passesMarched++;
		this.marchedPose = pass === 0;
	}

	/** Whether the target holds this pose. If not, it takes it, from this place. */
	private samePose(rays: ViewRays): boolean {
		const { pose, at } = this;
		const axes = rays.axes.elements;
		const { x, y, z, w } = rays.lens;
		let same =
			this.posed &&
			Math.hypot(at[0] - pose[0], at[1] - pose[1], at[2] - pose[2]) <= this.poseShift &&
			x === pose[12] &&
			y === pose[13] &&
			z === pose[14] &&
			w === pose[15];
		for (let i = 0; same && i < 9; i++) same = axes[i] === pose[3 + i];
		if (same) return true;
		pose.set(at);
		pose.set(axes, 3);
		pose[12] = x;
		pose[13] = y;
		pose[14] = z;
		pose[15] = w;
		this.origin[0] = at[0];
		this.origin[1] = at[1];
		this.origin[2] = at[2];
		this.posed = true;
		this.poses++;
		return false;
	}

	/**
	 * Note the length of a frame after a march of a new pose. A device whose
	 * median is over the budget takes the next step down, and is judged again;
	 * one under it keeps its plan for the session.
	 */
	private judge(frameMs: number): void {
		if (!this.judging || frameMs <= 0) return;
		this.judged[this.judgedCount++] = frameMs;
		if (this.judgedCount < JUDGED_FRAMES) return;
		this.judgedCount = 0;
		const median = [...this.judged].sort((a, b) => a - b)[JUDGED_FRAMES >> 1];
		if (median <= SLOW_FRAME_MS || this.rung >= LAST_RUNG) {
			this.judging = false;
			return;
		}
		this.rung++;
		console.warn(`[glow] moving frames take ${median.toFixed(1)} ms: step ${this.rung} down`);
		if (this.tierPlan) this.usePlan(stepDown(this.tierPlan, this.rung));
	}

	private draw(frame: GlowFrame, share: number): void {
		const { composite, screen } = this;
		if (!composite) return;
		const join = joinShare(Math.hypot(...this.at));
		// The sky inside the solar system: the emission alone once its map is made.
		const plan = this.plan;
		const sunDone = !!plan && this.sunPass >= plan.passes;
		const insideReady = this.sunEmission ? sunDone : this.regions !== null;
		this.insideFade.step(this.enabled && insideReady, frame.dtMs);
		const inside = this.insideFade.share * frame.skybox;
		const columns = this.dust.columns ?? null;
		const exposure = SUN_EXPOSURE * this.placeGain;
		const marched = share * join;
		if (marched > 0 && screen) composite.show(screen.external, exposure, marched);
		else composite.hide();
		// The sky from the Sun past the join, at the place's gain as the march.
		// The starless sky is asked for only here, so it loads at the join.
		const wanted = frame.skyboxLayer ? share * (1 - join) : 0;
		const sky = wanted > 0 ? this.skybox() : null;
		const fromSun = sky ? wanted : 0;
		const starless = sky ? (this.starless?.get() ?? null) : null;
		this.cubeShown = !!(this.cube && sky);
		if (this.cube && sky) {
			this.setCubeRays(frame.camera, sky);
			const texels: number = starless ? starless.userData.faceTexels : sky.faceTexels;
			const lod = Math.max(Math.log2(texels / SKYBOX_FACE_TEXELS), 0);
			this.cube.show(starless ?? sky.texture, this.placeGain, fromSun, lod);
		} else this.cube?.hide();
		const sun = this.sunEmission?.external;
		const emission = inside + this.insideFade.share * fromSun;
		if (this.inside && sun && emission > 0) this.inside.show(sun, exposure, emission);
		else this.inside?.hide();
		// The far regions are in the sky on both sides of the join.
		const regions = share + inside;
		if (this.regions && this.rays && columns && regions > 0) {
			const pixel = (2 * this.rays.lens.y) / Math.max(frame.heightPx, 1);
			this.regions.show(this.at, columns, exposure, regions, pixel);
		} else this.regions?.hide();
	}

	/** View to the cube's axes, as three draws the skybox. */
	private setCubeRays(camera: PerspectiveCamera, sky: SkyboxSource): void {
		const r = sky.rotation;
		_euler.set(-r.x, r.y, r.z, r.order);
		_camera.setFromMatrix4(camera.matrixWorld);
		this.cubeRays.axes.setFromMatrix4(_matrix.makeRotationFromEuler(_euler));
		this.cubeRays.axes.multiply(FLIP_X).multiply(_camera);
	}

	/** The sky from the Sun draws in the glow, so the UI credits it. */
	get skyFromSun(): boolean {
		return this.cubeShown;
	}

	/** Model light holds a visible share of the glow that shows, so the UI must
	 *  say the view is model. */
	get modelInView(): boolean {
		return (
			this.load.phase === 'ready' &&
			!!this.load.meta?.model &&
			this.fade.share > 0 &&
			joinShare(Math.hypot(...this.at)) >= LABEL_JOIN_SHARE
		);
	}

	/**
	 * The gain by place (`placeGain`) with the camera at `at` (tree axes, pc),
	 * for the dots. Null where no glow can draw: then the dots hold all the
	 * catalogue's light. 1 until the model's centre and the nest's axes are
	 * in: the dots then draw to the glow's cut, the least they draw to, so the
	 * walk fetches no box too early.
	 */
	dotsGain(at: Vec3): number | null {
		if (!this.tierPlan || this.load.phase === 'none') return null;
		const rotation = this.dust.frame?.rotation_to_icrs;
		const { meta } = this.load;
		if (!rotation || !meta) return 1;
		return placeGain(treeToNest(rotation, at), meta.model?.centre_pc ?? null);
	}

	/** True while a frame would change what draws. */
	busy(): boolean {
		if (this.load.phase === 'uploading') return this.dust.marchNest !== null;
		if (this.load.phase !== 'ready' || !this.plan) return false;
		if (this.fade.fading || this.insideFade.fading || this.starless?.loading) return true;
		if (this.enabled && this.sunEmission && this.sunPass < this.plan.passes) return true;
		// The passes at rest blend in, one a frame, while the march shows.
		return this.marching && this.posed && this.pass < Math.min(this.plan.passes, this.passLimit);
	}

	/** For the gates and the bench. */
	stats() {
		return {
			phase: this.load.phase,
			plan: this.plan,
			rung: this.rung,
			judging: this.judging,
			passes: this.passesMarched,
			poses: this.poses,
			pass: this.pass,
			target: this.screen ? [this.screen.width, this.screen.height] : null,
			origin: this.posed ? [...this.origin] : null,
			poseShift: this.poseShift,
			cut: GLOW_CUT_MAG,
			model: this.load.meta?.model ? true : false,
			clouds: this.clouds,
			modelInView: this.modelInView,
			placeGain: this.placeGain,
			joinShare: joinShare(Math.hypot(...this.at)),
			exposure: SUN_EXPOSURE * this.placeGain,
			share: this.fade.share,
			emission: this.load.meta?.emission
				? {
						parts: this.parts,
						sunMap: !!this.plan && this.sunPass >= this.plan.passes,
						insideShare: this.insideFade.share,
						regions: this.regions ? (this.regionRows?.light.length ?? 0) : 0
					}
				: null,
			busy: this.busy()
		};
	}

	dispose(): void {
		this.load.dispose();
		this.starless?.dispose();
	}
}

/** A throw of the glow's GPU objects would repeat on every frame. */
function noGlow(err: unknown): LoadPhase {
	console.warn('[glow] no glow on this device:', err);
	return 'none';
}
