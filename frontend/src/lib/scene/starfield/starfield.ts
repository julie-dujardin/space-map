/**
 * The stars of the Milky Way render tree. Nodes load and unload as the camera
 * moves.
 *
 * A node holds the stars of its box that stay visible from farthest away. The
 * magnitude of a box is the apparent magnitude, seen from the camera, of the
 * brightest star that the box can hold (`boxMagnitude`). No star of the box is
 * brighter. The magnitude of a parent is never above the magnitudes of its
 * children, so the walk reaches each child through its parent.
 *
 * The walk takes the boxes under the limit magnitude, brightest first, until
 * the point budget is full. The first box that the budget leaves out sets the
 * drawn limit to its magnitude. Thus that box holds no star bright enough to
 * show, and nothing pops in when it loads later. A box that can hold a very
 * bright star loads whatever the budget.
 *
 * The limit increases with the camera's distance from the barycentre, as an
 * exposure does. Near the Sun the sky stays as light as the skybox it takes
 * over from, and a zoom on another star keeps that star's sky. Zoomed out to
 * the galaxy, the budget sets what draws.
 *
 * Inside the solar system the skybox is the sky and the starfield loads
 * nothing. Past a distance from the barycentre it loads, and past a farther
 * one the skybox fades out (`band.ts`): it is the sky seen from the Sun. The
 * stars fade in once the nodes they want are in, and only where they can draw.
 *
 * Loaded nodes stay in a cache with a byte budget. The node wanted least
 * recently goes first. Each drawn node is one `Points` in tree coordinates
 * (pc, ICRS axes), under a group that takes them to the floating-origin scene.
 *
 * A click picks a star as it is drawn: the pick pass draws each node with the
 * same shader and uniforms. A node's ID file loads on the first pick in it.
 */

import {
	BufferAttribute,
	BufferGeometry,
	Color,
	Group,
	Mesh,
	Points,
	SphereGeometry,
	Vector3,
	type PerspectiveCamera,
	type Scene,
	type ShaderMaterial
} from 'three';
import { Container, nodeInfo, type NodeInfo } from '$lib/fetch/extrasolar/container';
import {
	ExtrasolarStaleError,
	extrasolarAllowed,
	extrasolarBase,
	extrasolarPath,
	fetchExtrasolarFile,
	fetchExtrasolarMetadata,
	type ExtrasolarCredit,
	type ExtrasolarTree
} from '$lib/fetch/extrasolar/files';
import { RetryBackoff } from '$lib/fetch/retry-backoff';
import { eagerMinorsDone } from '$lib/scene/setup/load-gates';
import { SwitchFade } from '$lib/scene/visibility/switch-fade';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { AU_SCALE, kmToScene } from '$lib/math/units';
import { makeStarSurfaceMaterial, updateStarTransition } from '../objects/sun';
import { PREFETCH_AU, RELEASE_AU, starsTakeSky } from './band';
import { photosphereColour, starColours } from './colour';
import {
	FOCUS_FLOOR_MAG,
	NO_FLOOR,
	makeStarMaterial,
	makeStarPickMaterial,
	starUniforms
} from './material';
import type { PickDraw } from '$lib/scene/interaction/gpu-pick';
import type { PickRegistry } from '$lib/scene/interaction/pick-registry';
import type { StarAnchor } from '$lib/types/objects';
import {
	PC_SCENE,
	boxDistance,
	boxMagnitude,
	childCentre,
	sceneToTree,
	treeMatrixElements,
	treeToScene,
	type Vec3
} from './tree';

/** The tree the starfield draws. */
const TREE = 'mw';
const ROOT = 'r';
/** Retry key of `metadata.json`. No node has this name. */
const METADATA = 'metadata.json';

/** Limit magnitude with the camera near its target. */
const BASE_LIMIT_MAG = 7.5;
/** Zoom distance (pc) past which the limit rises by 5 magnitudes per decade. */
const EXPOSURE_PC = 1;
/** A box that can hold a star this bright loads whatever the budget. The
 *  boxes near the camera have magnitudes far below any limit, and a small
 *  budget would leave the brightest stars out. */
const MUST_LOAD_MAG = 1;
/** A node's magnitude past the limit at which its load is dropped. */
const ABORT_MARGIN_MAG = 1;
/** Time constant of the drawn limit's approach to its target. */
const LIMIT_EASE_MS = 300;
/** Time for a node to fade in or out. */
const NODE_FADE_MS = 400;
/** Least time between two selections when nothing changed. */
const SELECT_EVERY_MS = 100;
/** Most nodes uploaded in one frame. */
const ADDS_PER_FRAME = 4;
/** Longest wait for the boot's minor bodies before the first node loads. */
const BOOT_GATE_MS = 10_000;
/** A magnitude no star reaches, for a focused star with none. */
const NO_MAGNITUDE = 99;
/** First of the transparent objects, because the stars are behind everything. */
const STAR_RENDER_ORDER = -1;
/** Pick ranges: a node's rows, and the focused star's own point. */
const NODE_PICK_PREFIX = 'star:';
const FOCUS_PICK_GROUP = 'star-focus';

export interface StarfieldBudget {
	/** Stars drawn at once. */
	points: number;
	/** Bytes of loaded nodes kept, drawn or not. */
	bytes: number;
	/** Node fetches at once. */
	fetches: number;
}

/** A drawn node, for picking and focusing. Its `Points` draws the rows of its
 *  file in file order, so a vertex index is a row of the node's ID file. */
export interface StarNodeView {
	name: string;
	rows: number;
	points: Points;
	container: Container;
	info: NodeInfo;
}

interface Loaded {
	container: Container;
	info: NodeInfo;
	geometry: BufferGeometry;
	bytes: number;
}

/** A pick range and the material that draws it, made on the first pick. */
interface PickRange {
	base: number;
	material: ShaderMaterial | null;
}

/** A star a click picked: the focused star, or a row of a drawn node. */
export type PickedStar = { id: number } | { node: string; row: number };

interface StarNode {
	name: string;
	depth: number;
	centre: Vec3;
	half: number;
	/** Largest visibility range in the node, pc at the tree's limit magnitude. */
	range: number;
	parent: StarNode | null;
	children: StarNode[];
	state: 'idle' | 'loading' | 'loaded';
	abort: AbortController | null;
	data: Loaded | null;
	points: Points | null;
	/** Magnitude of the box from the camera at the last selection. */
	magnitude: number;
	wanted: boolean;
	lastWantedMs: number;
	/** 0 to 1; drawn while above 0. */
	fade: number;
	/** The row of the focused star in this node, for the star it was found for. */
	hidden: { id: number; row: number } | null;
	/** Kept while the node is cached. */
	pick: PickRange | null;
	ids: { column: Float64Array; bytes: number } | null;
}

/** Whether the stars can draw. `unknown` until the tree's metadata is in. */
export type StarfieldAvailability = 'unknown' | 'yes' | 'no';

export interface StarfieldStats {
	drawnNodes: number;
	drawnPoints: number;
	cachedNodes: number;
	cachedBytes: number;
	loading: number;
	limit: number;
	targetLimit: number;
	/** Loading: the camera is past the prefetch distance. */
	active: boolean;
	/** The starfield's share of the sky. */
	share: number;
}

const _view = new Vector3();

export class StarfieldSystem {
	/** Tree coordinates to the floating-origin scene. */
	readonly group = new Group();
	private readonly uniforms = starUniforms();
	private tree: ExtrasolarTree | null = null;
	private credits: ExtrasolarCredit[] = [];
	private root: StarNode | null = null;
	private readonly nodes = new Map<string, StarNode>();
	private readonly drawn = new Set<StarNode>();
	private readonly retries = new RetryBackoff<string>(() => this.markDirty());
	/** ID files on their way, by node: a second click in the node waits for the same one. */
	private readonly idLoads = new Map<string, Promise<Float64Array>>();
	private loading = 0;
	private cachedBytes = 0;
	/** `no` when the map has no extrasolar base, opened without the layer,
	 *  or the metadata has no tree that this host may draw. */
	private drawable: StarfieldAvailability;
	private metadataLoading = false;
	private bootGate: Promise<void> | null = null;
	private stale = false;
	private disposed = false;
	private dirty = true;
	private lastSelectMs = -Infinity;
	private lastFrameMs = 0;
	private targetLimit = BASE_LIMIT_MAG;
	/** The limit that the wanted set allows. It is below the target when the budget is full. */
	private allowedLimit = BASE_LIMIT_MAG;
	private creditsShown = false;
	/** The camera is far enough from the barycentre for the starfield to load. */
	private active = false;
	/** The nodes wanted since loading started have come in. */
	private ready = false;
	/** The camera is out of the solar system. */
	private outside = false;
	/** The skybox leaves with this fade, whether the stars are in or not. */
	private readonly outsideFade = new SwitchFade();
	/** The starfield's share of the sky. */
	private readonly sky = new SwitchFade();
	private readonly matrix: number[] = [];
	/** The focused extrasolar object, drawn on its own at its record's place. */
	private focusStar: StarAnchor | null = null;
	private focusPoints: Points | null = null;
	private focusSurface: Mesh<SphereGeometry, ShaderMaterial> | null = null;
	private focusPick: PickRange | null = null;

	constructor(
		private readonly ctx: ContextManager,
		scene: Scene,
		private budget: StarfieldBudget,
		/** Called when something arrives that the next frame should draw. */
		private readonly onChange: () => void,
		private readonly pickRegistry: PickRegistry
	) {
		this.group.name = 'starfield';
		this.group.matrixAutoUpdate = false;
		this.group.visible = false;
		scene.add(this.group);
		const open = extrasolarBase() !== '' && !ctx.layers.skipped.has('starfield');
		this.drawable = open ? 'unknown' : 'no';
	}

	setBudget(budget: StarfieldBudget): void {
		this.budget = budget;
		this.markDirty();
	}

	/**
	 * The extrasolar object at the focus, or null. It draws at its record's
	 * place, which is exact where a node's float32 row is not, and whatever the
	 * drawn limit or the budget. Its row in the tree draws nothing meanwhile,
	 * so it is never drawn twice.
	 */
	setFocusStar(star: StarAnchor | null): void {
		const next = star?.tree ? star : null;
		if (next?.id === this.focusStar?.id) return;
		this.focusStar = next;
		if (this.focusSurface) {
			this.focusSurface.removeFromParent();
			this.focusSurface.geometry.dispose();
			this.focusSurface.material.dispose();
			this.focusSurface = null;
		}
		if (this.focusPoints) {
			this.focusPoints.removeFromParent();
			this.focusPoints.geometry.dispose();
			(this.focusPoints.material as ShaderMaterial).dispose();
			this.focusPoints = null;
		}
		this.dropPick(this.focusPick, FOCUS_PICK_GROUP);
		this.focusPick = null;
		if (next) {
			this.focusPoints = this.focusPoint(next);
			if (next.radiusKm !== null && Number.isFinite(next.radiusKm) && next.radiusKm > 0) {
				const colour = new Color(...photosphereColour(next.teff, next.colour));
				const surface = new Mesh(
					new SphereGeometry(kmToScene(next.radiusKm) / PC_SCENE, 96, 64),
					makeStarSurfaceMaterial(colour)
				);
				surface.name = 'star-photosphere';
				surface.position.copy(this.focusPoints.position);
				surface.updateMatrix();
				surface.matrixAutoUpdate = false;
				surface.visible = false;
				surface.renderOrder = STAR_RENDER_ORDER - 1;
				this.group.add(surface);
				this.focusSurface = surface;
			}
		}
		for (const node of this.drawn) if (node.points) this.applyHidden(node);
		this.onChange();
	}

	/** The tree being drawn, once its metadata is in. */
	treeEntry(): ExtrasolarTree | null {
		return this.tree;
	}

	/** Every drawn node. */
	drawnNodes(): StarNodeView[] {
		const out: StarNodeView[] = [];
		for (const node of this.drawn) {
			const view = this.view(node);
			if (view) out.push(view);
		}
		return out;
	}

	/** A loaded node by name, drawn or only cached. */
	node(name: string): StarNodeView | undefined {
		const node = this.nodes.get(name);
		return node ? this.view(node) : undefined;
	}

	/** What a pick pass draws for the stars: each drawn node in view and the
	 *  focused star. Empty while the starfield draws nothing. */
	pickDraws(): PickDraw[] {
		if (!this.group.visible) return [];
		const out: PickDraw[] = [];
		for (const node of this.drawn) {
			const points = node.points;
			if (!points?.visible || !node.data) continue;
			node.pick ??= {
				base: this.pickRegistry.allocateRows(
					NODE_PICK_PREFIX + node.name,
					node.data.container.rows
				),
				material: null
			};
			out.push({ points, material: this.pickMaterial(node.pick, points) });
		}
		const focus = this.focusPoints;
		if (focus?.visible) {
			this.focusPick ??= {
				base: this.pickRegistry.allocateRows(FOCUS_PICK_GROUP, 1),
				material: null
			};
			out.push({ points: focus, material: this.pickMaterial(this.focusPick, focus) });
		}
		return out;
	}

	/** The star of a pick-id from {@link pickDraws}, or null. */
	pickedStar(pickId: number): PickedStar | null {
		const at = this.pickRegistry.locate(pickId);
		if (!at) return null;
		if (at.groupId === FOCUS_PICK_GROUP) return this.focusStar ? { id: this.focusStar.id } : null;
		if (!at.groupId.startsWith(NODE_PICK_PREFIX)) return null;
		return { node: at.groupId.slice(NODE_PICK_PREFIX.length), row: at.row };
	}

	/** The ID of a picked star. A node's ID file loads on the first pick in it
	 *  and stays while the node is cached. */
	async starId(star: PickedStar): Promise<number> {
		if ('id' in star) return star.id;
		const ids = this.nodes.get(star.node)?.ids?.column ?? (await this.idsOf(star.node));
		const id = ids[star.row];
		if (!id) throw new Error(`[starfield] row ${star.row} of node ${star.node} has no ID`);
		return id;
	}

	private idsOf(name: string): Promise<Float64Array> {
		let load = this.idLoads.get(name);
		if (!load) {
			load = this.loadIds(name).finally(() => this.idLoads.delete(name));
			this.idLoads.set(name, load);
		}
		return load;
	}

	private async loadIds(name: string): Promise<Float64Array> {
		const tree = this.tree;
		if (!tree) throw new Error('[starfield] no tree to read IDs from');
		const container = await fetchExtrasolarFile(extrasolarPath(tree.ids, { name }), tree.token, {
			priority: 'high'
		});
		const node = this.nodes.get(name);
		const rows = node?.data?.container.rows;
		if (rows !== undefined && container.rows !== rows) {
			throw new Error(
				`[starfield] ID file of node ${name} has ${container.rows} rows, not ${rows}`
			);
		}
		const column = container.ids('id');
		if (node?.data && !node.ids) {
			node.ids = { column, bytes: container.buffer.byteLength };
			this.cachedBytes += container.buffer.byteLength;
		}
		return column;
	}

	private pickMaterial(range: PickRange, points: Points): ShaderMaterial {
		range.material ??= makeStarPickMaterial(points.material as ShaderMaterial, range.base);
		return range.material;
	}

	private dropPick(range: PickRange | null, groupId: string): void {
		if (!range) return;
		range.material?.dispose();
		this.pickRegistry.release(groupId);
	}

	/** Scene position (barycentre origin, scene units) of a row of a loaded
	 *  node. Its float32 offset from the node centre limits it to about
	 *  half · 2^-24 of the node; a close approach takes the record's position. */
	rowPosition(name: string, row: number): Vec3 | null {
		const data = this.nodes.get(name)?.data;
		if (!data || row < 0 || row >= data.container.rows) return null;
		const at = data.geometry.getAttribute('position').array as Float32Array;
		const [cx, cy, cz] = data.info.centre;
		const p = treeToScene(cx + at[3 * row], cy + at[3 * row + 1], cz + at[3 * row + 2], {
			x: 0,
			y: 0,
			z: 0
		});
		return [p.x, p.y, p.z];
	}

	stats(): StarfieldStats {
		let drawnPoints = 0;
		for (const node of this.drawn) drawnPoints += node.data?.container.rows ?? 0;
		let cachedNodes = 0;
		for (const node of this.nodes.values()) if (node.data) cachedNodes++;
		return {
			drawnNodes: this.drawn.size,
			drawnPoints,
			cachedNodes,
			cachedBytes: this.cachedBytes,
			loading: this.loading,
			limit: this.uniforms.uLimit.value,
			targetLimit: this.targetLimit,
			active: this.active,
			share: this.sky.share
		};
	}

	/** The starfield's share of the sky, 0 to 1. */
	share(): number {
		return this.sky.share;
	}

	/** The skybox's share of the sky, 0 to 1. Out of the solar system it is 0. */
	skyboxShare(): number {
		return 1 - this.outsideFade.share;
	}

	/** Local stars share exposure, but stay visible independently of the sky layer. */
	updateLocalStar(points: Points, focused: boolean): void {
		const uniforms = (points.material as ShaderMaterial).uniforms;
		uniforms.uLimit.value = this.uniforms.uLimit.value;
		uniforms.uPixelRatio.value = this.uniforms.uPixelRatio.value;
		uniforms.uFloor.value = focused ? FOCUS_FLOOR_MAG : NO_FLOOR;
	}

	/** Whether the stars can draw, so that the camera may leave the solar system. */
	availability(): StarfieldAvailability {
		return this.drawable;
	}

	/** True while a frame would change what draws. */
	busy(): boolean {
		if (this.loading > 0) return true;
		if (this.sky.fading || this.outsideFade.fading) return true;
		if (this.drawn.size === 0) return false;
		if (Math.abs(this.uniforms.uLimit.value - this.allowedLimit) > 0.01) return true;
		for (const node of this.drawn) {
			if (node.fade !== (node.wanted ? 1 : 0)) return true;
			if (node.wanted && node.data && !node.points) return true;
		}
		return false;
	}

	/**
	 * Per drawn frame. `focus` is the floating origin (scene units from the
	 * barycentre); `gain` dims the stars with the sky.
	 *
	 * The layer switch only decides what draws, as for every other layer. The
	 * nodes follow the camera while the layer is hidden, so a switch never
	 * sends a request. A layer switched off before the map opened never
	 * fetches.
	 */
	update(
		camera: PerspectiveCamera,
		focus: Vec3,
		pixelRatio: number,
		gain: number,
		nowMs: number,
		viewportHeight = 1
	): void {
		const dtMs = this.lastFrameMs ? Math.min(nowMs - this.lastFrameMs, 250) : 0;
		this.lastFrameMs = nowMs;
		const wx = camera.position.x + focus[0];
		const wy = camera.position.y + focus[1];
		const wz = camera.position.z + focus[2];
		const au = Math.hypot(wx, wy, wz) / AU_SCALE;
		const switchAu = Math.max(au, camera.position.length() / AU_SCALE);
		if (!this.active && au > PREFETCH_AU) this.active = true;
		else if (this.active && au < RELEASE_AU) this.stopLoading();
		if (this.active) this.start();

		const shown = this.ctx.layers.isVisible('starfield');
		this.outside = starsTakeSky(switchAu, this.outside);
		this.outsideFade.step(this.outside, dtMs);
		this.sky.step(shown && this.ready && this.root !== null && this.outside, dtMs);
		const skyShare = this.sky.share;
		this.group.visible = shown && this.root !== null && skyShare > 0;
		this.uniforms.uPixelRatio.value = pixelRatio;
		if (!this.root) return;

		this.group.matrix.fromArray(treeMatrixElements(focus, this.matrix));
		this.group.matrixWorldNeedsUpdate = true;

		const cam = sceneToTree(wx, wy, wz);
		const fromSunPc = Math.hypot(wx, wy, wz) / PC_SCENE;
		const target = BASE_LIMIT_MAG + 5 * Math.log10(Math.max(1, fromSunPc / EXPOSURE_PC));
		if (target !== this.targetLimit) this.dirty = true;
		this.targetLimit = target;

		const due = this.dirty || nowMs - this.lastSelectMs >= SELECT_EVERY_MS;
		if (this.active && !this.stale && due) {
			this.select(cam, nowMs);
		}

		const limit = this.uniforms.uLimit;
		const ease = dtMs > 0 ? 1 - Math.exp(-dtMs / LIMIT_EASE_MS) : 1;
		limit.value += (this.allowedLimit - limit.value) * ease;
		this.uniforms.uGain.value = gain * skyShare;
		this.updateFocusSurface(camera, focus, viewportHeight);

		this.applyFades(dtMs, camera, focus);
		if (this.group.visible && !this.creditsShown && this.drawn.size > 0) {
			this.creditsShown = true;
			this.ctx.credits.setStars(this.credits);
		}
	}

	private updateFocusSurface(camera: PerspectiveCamera, focus: Vec3, viewportHeight: number): void {
		const star = this.focusStar;
		const surface = this.focusSurface;
		const point = this.focusPoints;
		if (!surface || !point || !star?.scene || star.radiusKm === null) return;
		const distance = Math.hypot(
			star.scene[0] - focus[0] - camera.position.x,
			star.scene[1] - focus[1] - camera.position.y,
			star.scene[2] - focus[2] - camera.position.z
		);
		const radiusPx =
			((kmToScene(star.radiusKm) / distance) *
				camera.projectionMatrix.elements[5] *
				viewportHeight) /
			2;
		const share = updateStarTransition(surface.material, null, point, radiusPx);
		surface.visible = share > 0;
		surface.material.uniforms.uGain.value = this.uniforms.uGain.value;
	}

	dispose(): void {
		this.disposed = true;
		for (const node of this.nodes.values()) {
			node.abort?.abort();
			this.undraw(node);
			this.dropPick(node.pick, NODE_PICK_PREFIX + node.name);
			node.data?.geometry.dispose();
		}
		this.nodes.clear();
		this.setFocusStar(null);
		this.group.removeFromParent();
	}

	/** Back in the solar system: load nothing more, and let every node fade out.
	 *  The loaded ones stay in the cache. */
	private stopLoading(): void {
		this.active = false;
		this.ready = false;
		for (const node of this.nodes.values()) {
			node.wanted = false;
			node.abort?.abort();
		}
		this.markDirty();
	}

	/** Fetch the tree's metadata while the answer is unknown. A failed fetch
	 *  gives no answer, and is tried again after a wait. */
	private start(): void {
		if (this.drawable !== 'unknown' || this.metadataLoading) return;
		if (this.retries.waiting(METADATA)) return;
		this.metadataLoading = true;
		this.bootGate ??= Promise.race([
			eagerMinorsDone,
			new Promise<void>((resolve) => setTimeout(resolve, BOOT_GATE_MS))
		]);
		void (async () => {
			await this.bootGate;
			const meta = await fetchExtrasolarMetadata();
			const tree = meta?.trees[TREE];
			if (this.disposed) return;
			this.retries.clear(METADATA);
			if (!meta || !tree || !extrasolarAllowed(tree)) {
				this.noStars();
				return;
			}
			this.tree = tree;
			this.credits = meta.credits;
			this.root = this.record(ROOT, 0, tree.centre, tree.half_size, Infinity, null);
			this.drawable = 'yes';
			this.markDirty();
		})()
			.catch((err) => {
				if (this.disposed) return;
				console.warn('[starfield] metadata.json did not load:', err);
				this.retries.fail(METADATA);
			})
			.finally(() => {
				this.metadataLoading = false;
			});
	}

	/** No star draws this session: the camera goes back inside the solar system. */
	private noStars(): void {
		this.drawable = 'no';
		this.onChange();
	}

	private record(
		name: string,
		depth: number,
		centre: Vec3,
		half: number,
		range: number,
		parent: StarNode | null
	): StarNode {
		const node: StarNode = {
			name,
			depth,
			centre,
			half,
			range,
			parent,
			children: [],
			state: 'idle',
			abort: null,
			data: null,
			points: null,
			magnitude: Infinity,
			wanted: false,
			lastWantedMs: -Infinity,
			fade: 0,
			hidden: null,
			pick: null,
			ids: null
		};
		this.nodes.set(name, node);
		return node;
	}

	private markDirty(): void {
		this.dirty = true;
		this.onChange();
	}

	/** Walk the loaded tree from the root, brightest box first. */
	private select(cam: Vec3, nowMs: number): void {
		const tree = this.tree;
		const root = this.root;
		if (!tree || !root) return;
		this.dirty = false;
		this.lastSelectMs = nowMs;
		for (const node of this.nodes.values()) node.wanted = false;

		const magnitude = (node: StarNode) =>
			node === root
				? -Infinity
				: boxMagnitude(boxDistance(cam, node.centre, node.half), node.range, tree.range_limit_mag);
		const heap = new NodeHeap();
		root.magnitude = magnitude(root);
		heap.push(root);
		let points = 0;
		let allowed = this.targetLimit;
		const wanted: StarNode[] = [];
		for (let node = heap.pop(); node; node = heap.pop()) {
			if (node.magnitude > this.targetLimit) break;
			// Rows are known once a node is in; until then a full node is assumed.
			const rows = node.data?.container.rows ?? tree.node_rows;
			if (points + rows > this.budget.points && node.magnitude > MUST_LOAD_MAG) {
				allowed = node.magnitude;
				break;
			}
			points += rows;
			node.wanted = true;
			node.lastWantedMs = nowMs;
			wanted.push(node);
			for (const child of node.children) {
				child.magnitude = magnitude(child);
				heap.push(child);
			}
		}
		this.allowedLimit = allowed;
		if (wanted.every((node) => node.data || this.retries.waiting(node.name))) this.ready = true;

		for (const node of wanted) {
			if (this.loading >= this.budget.fetches) break;
			if (node.state === 'idle' && !this.retries.waiting(node.name)) this.load(node);
		}
		for (const node of this.nodes.values()) {
			if (node.state !== 'loading' || node.wanted) continue;
			if (node.magnitude > allowed + ABORT_MARGIN_MAG || !node.parent?.wanted) {
				node.abort?.abort();
			}
		}
		for (const node of wanted) if (node.data) this.drawn.add(node);
		this.evict();
	}

	private load(node: StarNode): void {
		const tree = this.tree;
		if (!tree) return;
		node.state = 'loading';
		this.loading++;
		const abort = new AbortController();
		node.abort = abort;
		fetchExtrasolarFile(extrasolarPath(tree.node, { name: node.name }), tree.token, {
			signal: abort.signal,
			priority: 'low'
		})
			.then((container) => {
				if (this.disposed) return;
				this.retries.clear(node.name);
				this.adopt(node, container);
			})
			.catch((err: unknown) => {
				node.state = 'idle';
				if (this.disposed || abort.signal.aborted) return;
				if (err instanceof ExtrasolarStaleError) {
					// The files are from a newer export than the tab's metadata. Load no more.
					this.stale = true;
					return;
				}
				this.retries.fail(node.name);
				console.warn(`[starfield] node ${node.name} did not load:`, err);
			})
			.finally(() => {
				this.loading--;
				node.abort = null;
				this.markDirty();
			});
	}

	private adopt(node: StarNode, container: Container): void {
		const info = nodeInfo(container);
		const rows = container.rows;
		const x = container.float32('x');
		const y = container.float32('y');
		const z = container.float32('z');
		const position = new Float32Array(3 * rows);
		for (let i = 0; i < rows; i++) {
			position[3 * i] = x[i];
			position[3 * i + 1] = y[i];
			position[3 * i + 2] = z[i];
		}
		const colour = starColours(container.float32('colour'), new Uint8Array(3 * rows));
		const geometry = new BufferGeometry();
		geometry.setAttribute('position', new BufferAttribute(position, 3));
		geometry.setAttribute('mag', new BufferAttribute(container.float32('mag'), 1));
		geometry.setAttribute('starColour', new BufferAttribute(colour, 3, true));
		const bytes = container.buffer.byteLength + position.byteLength + colour.byteLength;
		node.data = { container, info, geometry, bytes };
		node.state = 'loaded';
		node.centre = info.centre;
		node.half = info.half;
		node.range = info.maxRange;
		this.cachedBytes += bytes;
		node.children = [];
		for (let k = 0; k < 8; k++) {
			if (!((info.childMask >> k) & 1)) continue;
			node.children.push(
				this.record(
					node.name + k,
					node.depth + 1,
					childCentre(info.centre, info.half, k),
					info.half / 2,
					info.childRange[k],
					node
				)
			);
		}
	}

	/** Drop the least recently wanted nodes past the byte budget; a node goes
	 *  after its children. */
	private evict(): void {
		if (this.cachedBytes <= this.budget.bytes) return;
		const candidates = [...this.nodes.values()].filter(
			(node) =>
				node.data &&
				!node.wanted &&
				!node.points &&
				node.children.every((child) => child.state === 'idle' && !child.data)
		);
		candidates.sort((a, b) => a.lastWantedMs - b.lastWantedMs || b.depth - a.depth);
		for (const node of candidates) {
			if (this.cachedBytes <= this.budget.bytes) break;
			// A child dropped earlier in this pass leaves its parent free to go next time.
			if (node.children.some((child) => child.data)) continue;
			this.release(node);
		}
	}

	private release(node: StarNode): void {
		const data = node.data;
		if (!data) return;
		data.geometry.dispose();
		this.cachedBytes -= data.bytes;
		node.data = null;
		node.state = 'idle';
		node.hidden = null;
		this.dropPick(node.pick, NODE_PICK_PREFIX + node.name);
		node.pick = null;
		if (node.ids) this.cachedBytes -= node.ids.bytes;
		node.ids = null;
		for (const child of node.children) this.forget(child);
		node.children = [];
	}

	/** Drop the records of a subtree that holds no data. */
	private forget(node: StarNode): void {
		for (const child of node.children) this.forget(child);
		this.nodes.delete(node.name);
	}

	/** Step the fades, add the nodes that came in, cull the drawn ones to the
	 *  view and take out the ones that faded away. */
	private applyFades(dtMs: number, camera: PerspectiveCamera, focus: Vec3): void {
		const step = dtMs / NODE_FADE_MS;
		let adds = 0;
		const view = new ViewCone(camera);
		for (const node of [...this.drawn]) {
			const target = node.wanted ? 1 : 0;
			if (!node.points) {
				if (!node.wanted || !node.data || adds >= ADDS_PER_FRAME) {
					if (!node.wanted) this.drawn.delete(node);
					continue;
				}
				adds++;
				this.draw(node);
			}
			if (target > node.fade) node.fade = Math.min(node.fade + step, 1);
			else if (target < node.fade) node.fade = Math.max(node.fade - step, 0);
			if (node.fade === 0 && !node.wanted) {
				this.undraw(node);
				this.drawn.delete(node);
				continue;
			}
			const points = node.points!;
			(points.material as ShaderMaterial).uniforms.uFade.value = node.fade;
			points.visible = view.sees(node, focus);
		}
	}

	private draw(node: StarNode): void {
		const data = node.data!;
		const points = new Points(data.geometry, makeStarMaterial(this.uniforms));
		points.position.set(...data.info.centre);
		points.updateMatrix();
		points.matrixAutoUpdate = false;
		// Culled here against the view cone: three's frustum has a far plane,
		// and a star past it draws on it.
		points.frustumCulled = false;
		points.renderOrder = STAR_RENDER_ORDER;
		points.userData.starNode = node.name;
		node.points = points;
		node.fade = 0;
		this.applyHidden(node);
		this.group.add(points);
	}

	/** One point at the focused star's place, in the tree's frame. */
	private focusPoint(star: StarAnchor): Points {
		const geometry = new BufferGeometry();
		geometry.setAttribute('position', new BufferAttribute(new Float32Array(3), 3));
		// No magnitude in the record: it draws at the limit.
		const mag = star.absMag ?? NO_MAGNITUDE;
		geometry.setAttribute('mag', new BufferAttribute(new Float32Array([mag]), 1));
		const colour = starColours(new Float32Array([star.colour ?? NaN]), new Uint8Array(3));
		geometry.setAttribute('starColour', new BufferAttribute(colour, 3, true));
		const material = makeStarMaterial(this.uniforms, FOCUS_FLOOR_MAG);
		material.uniforms.uFade.value = 1;
		const points = new Points(geometry, material);
		points.position.set(...star.tree!);
		points.updateMatrix();
		points.matrixAutoUpdate = false;
		points.frustumCulled = false;
		points.renderOrder = STAR_RENDER_ORDER;
		points.userData.focusStar = star.id;
		this.group.add(points);
		return points;
	}

	/** Hide the focused star's row in a drawn node, where the node holds it. */
	private applyHidden(node: StarNode): void {
		const star = this.focusStar;
		let row = -1;
		if (star && node.data) {
			if (node.hidden?.id !== star.id) {
				node.hidden = { id: star.id, row: findStarRow(node.data, star) };
			}
			row = node.hidden.row;
		}
		(node.points!.material as ShaderMaterial).uniforms.uHidden.value = row;
	}

	private undraw(node: StarNode): void {
		const points = node.points;
		if (!points) return;
		points.removeFromParent();
		(points.material as ShaderMaterial).dispose();
		// It holds the uniforms of the material that went; a redraw makes both again.
		if (node.pick) {
			node.pick.material?.dispose();
			node.pick.material = null;
		}
		// Frees the GPU buffers; the arrays stay in the cache for a redraw.
		node.data?.geometry.dispose();
		node.points = null;
		node.fade = 0;
	}

	private view(node: StarNode): StarNodeView | undefined {
		const data = node.data;
		if (!data || !node.points) return undefined;
		return {
			name: node.name,
			rows: data.container.rows,
			points: node.points,
			container: data.container,
			info: data.info
		};
	}
}

/** Two float32 steps: the record's place, computed again here, can round
 *  one step off the stored offset. */
const ROW_STEPS = 2 ** -22;
/** Floor of the match distance (pc) for a row at the node centre. */
const ROW_FLOOR_PC = 1e-9;
/** The tree rounds magnitudes to 1/1024. */
const ROW_MAG = 0.01;

/**
 * The row of `star` in a node, or -1 when the node does not hold it. A row
 * is the star when its float32 offset is the record's place to within the
 * rounding, and its magnitude is the record's.
 */
export function findStarRow(
	data: { container: Container; info: NodeInfo },
	star: Pick<StarAnchor, 'tree' | 'absMag'>
): number {
	const tree = star.tree;
	if (!tree) return -1;
	const { centre, half } = data.info;
	const ox = tree[0] - centre[0];
	const oy = tree[1] - centre[1];
	const oz = tree[2] - centre[2];
	if (Math.max(Math.abs(ox), Math.abs(oy), Math.abs(oz)) > half * (1 + 1e-6)) return -1;
	const tx = Math.abs(ox) * ROW_STEPS + ROW_FLOOR_PC;
	const ty = Math.abs(oy) * ROW_STEPS + ROW_FLOOR_PC;
	const tz = Math.abs(oz) * ROW_STEPS + ROW_FLOOR_PC;
	const c = data.container;
	const x = c.float32('x');
	const y = c.float32('y');
	const z = c.float32('z');
	const mag = c.float32('mag');
	let best = -1;
	let bestDistance = Infinity;
	for (let i = 0; i < c.rows; i++) {
		const dx = Math.abs(x[i] - ox);
		const dy = Math.abs(y[i] - oy);
		const dz = Math.abs(z[i] - oz);
		if (dx > tx || dy > ty || dz > tz) continue;
		if (star.absMag !== null && Math.abs(mag[i] - star.absMag) > ROW_MAG) continue;
		const distance = dx + dy + dz;
		if (distance < bestDistance) {
			best = i;
			bestDistance = distance;
		}
	}
	return best;
}

/** The camera's view without its far plane, for culling node boxes. */
class ViewCone {
	private readonly tanY: number;
	private readonly tanX: number;
	private readonly inverse: PerspectiveCamera['matrixWorldInverse'];

	constructor(camera: PerspectiveCamera) {
		this.tanY = Math.tan(((camera.fov / 2) * Math.PI) / 180) / camera.zoom;
		this.tanX = this.tanY * camera.aspect;
		this.inverse = camera.matrixWorldInverse;
	}

	/** Whether the bounding sphere of a node's box meets the view. */
	sees(node: StarNode, focus: Vec3): boolean {
		const [cx, cy, cz] = node.centre;
		const at = treeToScene(cx, cy, cz, _view);
		_view.set(at.x - focus[0], at.y - focus[1], at.z - focus[2]).applyMatrix4(this.inverse);
		const r = node.half * Math.sqrt(3) * PC_SCENE;
		const depth = -_view.z;
		if (depth < -r) return false;
		// Distance from the centre to each side plane, along its normal.
		const sideX = (Math.abs(_view.x) - depth * this.tanX) / Math.hypot(1, this.tanX);
		const sideY = (Math.abs(_view.y) - depth * this.tanY) / Math.hypot(1, this.tanY);
		return sideX <= r && sideY <= r;
	}
}

/** A binary min-heap of nodes on their magnitude. */
class NodeHeap {
	private readonly items: StarNode[] = [];

	push(node: StarNode): void {
		const items = this.items;
		items.push(node);
		let i = items.length - 1;
		while (i > 0) {
			const up = (i - 1) >> 1;
			if (items[up].magnitude <= items[i].magnitude) break;
			[items[up], items[i]] = [items[i], items[up]];
			i = up;
		}
	}

	pop(): StarNode | undefined {
		const items = this.items;
		const top = items[0];
		const last = items.pop();
		if (items.length > 0 && last) {
			items[0] = last;
			let i = 0;
			for (;;) {
				const l = 2 * i + 1;
				const r = l + 1;
				let min = i;
				if (l < items.length && items[l].magnitude < items[min].magnitude) min = l;
				if (r < items.length && items[r].magnitude < items[min].magnitude) min = r;
				if (min === i) break;
				[items[min], items[i]] = [items[i], items[min]];
				i = min;
			}
		}
		return top;
	}
}
