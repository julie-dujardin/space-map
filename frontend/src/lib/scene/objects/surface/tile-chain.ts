import {
	type AnyPixelFormat,
	type ColorSpace,
	DataArrayTexture,
	LinearFilter,
	LinearMipmapLinearFilter,
	Matrix4,
	type Object3D,
	type PerspectiveCamera,
	RedFormat,
	RepeatWrapping,
	type Texture,
	type TextureDataType,
	UnsignedByteType,
	Vector2,
	Vector3,
	Vector4,
	type WebGLRenderer
} from 'three';
import { tileUrl } from '$lib/fetch/data-base';
import {
	CAP_EDGE,
	CHART_FOLDER,
	type Chart,
	FIRST_TILE_LEVEL,
	MAP,
	NORTH,
	SOUTH,
	WINDOW_TILES,
	type WindowPlacement,
	cameraChart,
	chartColumns,
	chartPoint,
	chartRows,
	deepestLevel,
	mapTileVersion,
	patchOfTile,
	placeWindow,
	slotTile,
	windowChain,
	windowHome
} from '$lib/scene/lod/tile-window';
import type { TilesBlock } from '$lib/scene/types';
import { MAX_ANISOTROPY } from './anisotropy';

/**
 * A chain of tile windows of one pyramid, kept on the ground under the camera.
 *
 * Each window is a block of tiles around the point under the camera: the
 * finest at the level the screen needs there, each next one a level coarser
 * and so twice as wide, for the ground further out. A window has no mipmaps:
 * the next one is its mipmap. A slot whose tile is missing is masked off, so
 * a slow or unreachable tile host only costs detail.
 *
 * Near a pole the windows are on that pole's cap, where a tile is as wide on
 * the ground as it is tall. A window that changes chart loads on a spare
 * layer while the one it replaces stays drawn, so the change does not show.
 *
 * Near a patch the chain goes past the pyramid's finest level, as deep as a
 * window still reaches the patch. Those levels have tiles on the ground of the
 * patch only, so the chain's last windows stay on the pyramid's own levels,
 * for the ground around it.
 */

/** Windows a chain can hold. A device holds as many as its tier allows. */
export const MAX_WINDOWS = 6;

/** Windows drawn at once: the chain, and one on its way out. */
export const MAX_DRAWN = MAX_WINDOWS + 1;

/** Tile fetches in flight per chain. */
const MAX_INFLIGHT = 6;

/** Failed fetches after which the pyramid is given up for the session: the
 *  host is down or does not carry it, and the tiers are the fallback. */
const MAX_FAILURES = 4;

/** Seconds a tile may take. A host that hangs, as a server on an absent
 *  network mount does, must count as failed like one that refuses. */
const FETCH_TIMEOUT_S = 30;

/** Seconds a chain's windows outlive the last frame that needed them. */
const IDLE_DISPOSE_S = 5;

/** Width of the fade at a window's edge, in tiles. */
const FEATHER_TILES = 0.5;

const SLOTS = WINDOW_TILES * WINDOW_TILES;

/** One decoded tile, as a texture the renderer can copy into a window. */
export interface LoadedTile {
	texture: Texture;
	release(): void;
}

/** What a pyramid's tiles hold, and how they reach the window texture. */
export interface TileKind {
	format: AnyPixelFormat;
	type: TextureDataType;
	colorSpace: ColorSpace;
	/** Fetch and decode one tile, south row first: the window is stored north up. */
	load(url: string, signal: AbortSignal): Promise<LoadedTile>;
}

/** One layer of the window texture: a window of one level of one chart. */
interface TileWindow {
	layer: number;
	chart: Chart;
	level: number;
	placement?: WindowPlacement;
	frame?: number;
	/** Place in the chain, finest first; past it for a window on its way out. */
	rank: number;
	/** Per slot: the tile it shows or waits for. */
	wanted: (string | undefined)[];
	/** Per slot: the fetch in flight, keyed like `wanted`. */
	pending: Map<number, { key: string; abort: AbortController }>;
}

interface WindowStore {
	/** What its layers hold: a chain that takes another kind starts over. */
	kind: TileKind;
	/** Every window, one layer each, and one layer to spare. */
	texture: DataArrayTexture;
	/** Per layer, a row of slots per tile row: 255 where the tile is in. */
	mask: DataArrayTexture;
	windows: TileWindow[];
	free: number[];
	tileSize: number;
}

export interface TileChain {
	kind: TileKind;
	/** Its levels past the pyramid are at even steps: see `windowChain`. */
	spread: boolean;
	store?: WindowStore;
	uniforms: {
		map: { value: DataArrayTexture | null };
		mask: { value: DataArrayTexture | null };
		/** Per window, finest first: columns and rows of its level, then its north-west tile. */
		grid: { value: Vector4[] };
		/** Per window: its chart, its layer, its level, and 1 while it is drawn. */
		window: { value: Vector4[] };
		/** Per map window: the point under the camera, in tiles from its north-west corner. */
		home: { value: Vector2[] };
		/** The point under the camera, in the mesh's own frame. */
		anchor: { value: Vector3 };
		/** Per window: a bit per slot, set where its tile is in. For a reader
		 *  that cannot afford a look at the mask each time. */
		loaded: { value: Int32Array };
		/** Most taps of the anisotropic filter, and a tile's side in pixels. */
		filter: { value: Vector2 };
	};
	/** Chart of the camera's own windows, kept near the line between two. */
	chart?: Chart;
	inflight: number;
	/** Fetches failed in a row, and the tiles they were for: not asked again. */
	failures: number;
	failed: Set<string>;
	/** The tile host could not serve this pyramid; the tiers stand alone. */
	dead: boolean;
	/** `performance.now()` of the last frame that wanted windows. */
	lastUsed: number;
}

/**
 * Fragment code shared by every shader that reads a chain: where the fragment
 * is on the charts, and how much of one window shows there. Guarded, since
 * two chains can be on one material.
 */
export const TILE_CHAIN_GLSL = /* glsl */ `
#ifndef TILE_CHAIN
#define TILE_CHAIN

// Where a fragment is on the map and on the cap of its own hemisphere, as
// fractions of the chart, and what a screen pixel spans there. The place on
// the cap is from the chart's north-west corner. The place on the map is from
// the point that the maker of the charts counts from.
struct TileCharts {
	vec2 mapAt;
	vec2 mapDx;
	vec2 mapDy;
	vec2 capAt;
	vec2 capDx;
	vec2 capDy;
	float side;
};

// The cap of the hemisphere of dir, seen from above its pole. ddx and ddy are
// what a screen pixel adds to dir.
void tileCap( vec3 dir, vec3 ddx, vec3 ddy, out float side, out vec2 capAt, out vec2 capDx, out vec2 capDy ) {
	side = dir.y < 0.0 ? - 1.0 : 1.0;
	float fold = 1.0 + side * dir.y;
	vec2 plane = vec2( dir.x, side * dir.z );
	float capScale = 0.5 / ( ${CAP_EDGE.toFixed(8)} * fold );
	capAt = 0.5 + plane * capScale;
	capDx = ( vec2( ddx.x, side * ddx.z ) - plane * ( side * ddx.y / fold ) ) * capScale;
	capDy = ( vec2( ddy.x, side * ddy.z ) - plane * ( side * ddy.y / fold ) ) * capScale;
}

// The charts of the point at + off, the map counted from at. A position on
// the sphere has seven digits, and a tile index of a patch takes them all;
// the offset keeps its own.
TileCharts tileChartsFrom( vec3 at, vec3 off ) {
	TileCharts charts;
	vec3 pos = at + off;
	vec3 ox = dFdx( off );
	vec3 oy = dFdy( off );

	// The turn about the axis and the drop from the north pole, each as the
	// angle between at and the point.
	float flat2 = max( pos.x * pos.x + pos.z * pos.z, 1e-30 );
	float flat1 = sqrt( flat2 );
	float flat0 = sqrt( at.x * at.x + at.z * at.z );
	float turn = atan( at.z * off.x - at.x * off.z, at.x * pos.x + at.z * pos.z );
	float out1 = ( 2.0 * ( at.x * off.x + at.z * off.z ) + off.x * off.x + off.z * off.z ) / ( flat1 + flat0 );
	float drop = atan( out1 * at.y - off.y * flat0, pos.y * at.y + flat1 * flat0 );
	charts.mapAt = vec2( turn / ( 2.0 * PI ), drop / PI );
	float east = 1.0 / ( 2.0 * PI * flat2 );
	float south = 1.0 / ( PI * dot( pos, pos ) );
	charts.mapDx = vec2( ( pos.z * ox.x - pos.x * ox.z ) * east, ( pos.y * ( pos.x * ox.x + pos.z * ox.z ) / flat1 - flat1 * ox.y ) * south );
	charts.mapDy = vec2( ( pos.z * oy.x - pos.x * oy.z ) * east, ( pos.y * ( pos.x * oy.x + pos.z * oy.z ) / flat1 - flat1 * oy.y ) * south );

	// A cap goes no deeper than the pyramid, so the direction itself will do.
	float range = length( pos );
	vec3 dir = pos / range;
	vec3 ddx = ( ox - dir * dot( dir, ox ) ) / range;
	vec3 ddy = ( oy - dir * dot( dir, oy ) ) / range;
	tileCap( dir, ddx, ddy, charts.side, charts.capAt, charts.capDx, charts.capDy );
	return charts;
}

// Long and short half-axes of the footprint whose sides are fx and fy. The
// two sides alone would do where the stretch runs along the screen's axes;
// around a pole it runs every way, and each side then holds most of it.
void tileAxes( vec2 fx, vec2 fy, out vec2 major, out vec2 minor ) {
	float p = fx.x * fx.x + fy.x * fy.x;
	float q = fx.y * fx.y + fy.y * fy.y;
	float r = fx.x * fx.y + fy.x * fy.y;
	float det = fx.x * fy.y - fx.y * fy.x;
	float hi = 0.5 * ( p + q ) + sqrt( 0.25 * ( p - q ) * ( p - q ) + r * r );
	float lo = det * det / max( hi, 1e-30 );
	vec2 axis = p >= q ? vec2( hi - q, r ) : vec2( r, hi - p );
	float len = length( axis );
	axis = len > 0.0 ? axis / len : vec2( 1.0, 0.0 );
	major = axis * sqrt( hi );
	minor = vec2( - axis.y, axis.x ) * sqrt( lo );
}

// How much of a window shows at the fragment, before the mask of its tiles.
// home is the point that the charts count the map from, in tiles from the
// window's north-west corner. Gives the fragment's place in the window's
// texture, in tiles, and the axes of its footprint, in the window's pixels.
float tileWindowWeight( TileCharts charts, vec4 window, vec4 grid, vec2 home, vec2 tileFilter, out vec2 spot, out vec2 major, out vec2 minor ) {
	bool onMap = window.x < 0.5;
	// The other pole's cap.
	if ( ! onMap && ( window.x < 1.5 ) != ( charts.side > 0.0 ) ) return 0.0;
	vec2 dx = ( onMap ? charts.mapDx : charts.capDx ) * grid.xy * tileFilter.y;
	vec2 dy = ( onMap ? charts.mapDy : charts.capDy ) * grid.xy * tileFilter.y;

	// Level this fragment asks of the window, from the short axis of its
	// footprint in the window's pixels: the long axis is the anisotropic
	// filter's to cover, as far as its taps reach. The window fades in
	// over the level below its own, as a mipmap would.
	tileAxes( dx, dy, major, minor );
	float foot = max( length( minor ), length( major ) / tileFilter.x );
	float weight = clamp( 1.0 - log2( max( foot, 1e-6 ) ), 0.0, 1.0 );
	if ( weight <= 0.0 ) return 0.0;

	float rows = ${WINDOW_TILES.toFixed(1)};
	// Offset from the window's north-west corner, in tiles.
	vec2 rel = onMap ? home + charts.mapAt * grid.xy : charts.capAt * grid.xy - grid.zw;
	if ( onMap ) {
		// Half a pixel in from a pole of the map: past it the filter would
		// read the far row. The map's longitude wraps.
		rel.y = clamp( rel.y, 0.0005 - grid.w, grid.y - 0.0005 - grid.w );
		rel.x = mod( rel.x, grid.x );
	}
	if ( rel.x < 0.0 || rel.x > rows || rel.y < 0.0 || rel.y > rows ) return 0.0;
	// Distance to the window's edge, in tiles. A pole of the map is no
	// edge: nothing lies past it.
	vec2 near = min( rel, rows - rel );
	if ( onMap && grid.w < 0.5 ) near.y = rows - rel.y;
	if ( onMap && grid.w + rows > grid.y - 0.5 ) near.y = grid.w < 0.5 ? rows : rel.y;
	// The texture repeats every window: a tile sits in the slot its own
	// column and row pick, north up.
	spot = rel + mod( grid.zw, rows );
	return weight * smoothstep( 0.0, ${FEATHER_TILES.toFixed(2)}, min( near.x, near.y ) );
}

#endif
`;

export function createChain(kind: TileKind, spread = false): TileChain {
	return {
		kind,
		spread,
		uniforms: {
			map: { value: null },
			mask: { value: null },
			grid: { value: Array.from({ length: MAX_DRAWN }, () => new Vector4()) },
			window: { value: Array.from({ length: MAX_DRAWN }, () => new Vector4()) },
			home: { value: Array.from({ length: MAX_DRAWN }, () => new Vector2()) },
			anchor: { value: new Vector3(1, 0, 0) },
			loaded: { value: new Int32Array(MAX_DRAWN) },
			filter: { value: new Vector2(1, 1) }
		},
		inflight: 0,
		failures: 0,
		failed: new Set(),
		dead: false,
		lastUsed: 0
	};
}

function createStore(
	kind: TileKind,
	tileSize: number,
	layers: number,
	renderer: WebGLRenderer
): WindowStore {
	const size = tileSize * WINDOW_TILES;
	const texture = new DataArrayTexture(null, size, size, layers);
	// Storage only: the tiles are copied in as they arrive.
	texture.source.dataReady = false;
	texture.format = kind.format;
	texture.type = kind.type;
	texture.colorSpace = kind.colorSpace;
	texture.wrapS = texture.wrapT = RepeatWrapping;
	texture.magFilter = LinearFilter;
	// The renderer only passes anisotropy on with a mipmap filter. The texture
	// has one level, so this filter reads the same pixels as a linear one.
	texture.minFilter = LinearMipmapLinearFilter;
	texture.generateMipmaps = false;
	texture.anisotropy = Math.min(MAX_ANISOTROPY, renderer.capabilities.getMaxAnisotropy());
	texture.needsUpdate = true;

	const mask = new DataArrayTexture(
		new Uint8Array(SLOTS * layers),
		WINDOW_TILES,
		WINDOW_TILES,
		layers
	);
	mask.format = RedFormat;
	mask.type = UnsignedByteType;
	// Filtered, a reader can tell a tile whose neighbour is missing.
	mask.minFilter = mask.magFilter = LinearFilter;
	mask.wrapS = mask.wrapT = RepeatWrapping;
	mask.unpackAlignment = 1;
	mask.needsUpdate = true;

	const free = Array.from({ length: layers }, (_, layer) => layer);
	return { kind, texture, mask, windows: [], free, tileSize };
}

function setLoaded(store: WindowStore, layer: number, slot: number, loaded: boolean): void {
	(store.mask.image.data as Uint8Array)[layer * SLOTS + slot] = loaded ? 255 : 0;
	store.mask.needsUpdate = true;
}

function isLoaded(store: WindowStore, layer: number, slot: number): boolean {
	return (store.mask.image.data as Uint8Array)[layer * SLOTS + slot] !== 0;
}

/** Point a window at `placement`: slots whose tile changed go blank and wait. */
function retarget(
	store: WindowStore,
	win: TileWindow,
	placement: WindowPlacement,
	frame: number | undefined
): void {
	if (win.placement === placement && win.frame === frame) return;
	win.placement = placement;
	win.frame = frame;
	for (let slot = 0; slot < SLOTS; slot++) {
		const { x, y } = slotTile(placement, slot % WINDOW_TILES, Math.floor(slot / WINDOW_TILES));
		const key = `${frame ?? 0}/${win.chart}/${win.level}/${x}/${y}`;
		if (win.wanted[slot] === key) continue;
		win.wanted[slot] = key;
		setLoaded(store, win.layer, slot, false);
		const stale = win.pending.get(slot);
		if (stale) {
			stale.abort.abort();
			win.pending.delete(slot);
		}
	}
}

/** Give a window's layer back, blank. */
function release(store: WindowStore, win: TileWindow): void {
	for (const { abort } of win.pending.values()) abort.abort();
	win.pending.clear();
	for (let slot = 0; slot < SLOTS; slot++) setLoaded(store, win.layer, slot, false);
	store.free.push(win.layer);
}

/** The patch a tile past the pyramid's finest level belongs to. Such a level
 *  has tiles on the ground of its patches only. */
function patchOf(tiles: TilesBlock, win: TileWindow, tile: { x: number; y: number }) {
	if (win.chart !== MAP || win.level <= tiles.max_level) return undefined;
	return patchOfTile(tiles.patches, win.level, tile.x, tile.y);
}

/** Whether the tile of a slot exists at all. */
function exists(tiles: TilesBlock, win: TileWindow, slot: number): boolean {
	if (win.level <= tiles.max_level) return true;
	if (!win.placement) return false;
	const tile = slotTile(win.placement, slot % WINDOW_TILES, Math.floor(slot / WINDOW_TILES));
	return patchOf(tiles, win, tile) !== undefined;
}

/** Whether every tile of the window is in, or will not come. */
function settled(
	chain: TileChain,
	store: WindowStore,
	tiles: TilesBlock,
	win: TileWindow
): boolean {
	for (let slot = 0; slot < SLOTS; slot++) {
		const key = win.wanted[slot];
		if (!key) return false;
		if (isLoaded(store, win.layer, slot) || chain.failed.has(key)) continue;
		if (exists(tiles, win, slot)) return false;
	}
	return true;
}

const copyAt = new Vector3();
const queue: { slot: number; far: number }[] = [];

/** Start fetches for the blank slots of one window, those nearest the chart
 *  point `(x, y)` first. */
function pump(
	chain: TileChain,
	store: WindowStore,
	tiles: TilesBlock,
	win: TileWindow,
	x: number,
	y: number,
	renderer: WebGLRenderer,
	invalidate: () => void
): void {
	const placement = win.placement;
	if (!placement) return;
	const columns = chartColumns(win.chart, win.level);
	const cx = x * columns;
	const cy = y * chartRows(win.chart, win.level);

	queue.length = 0;
	for (let slot = 0; slot < SLOTS; slot++) {
		const key = win.wanted[slot];
		if (!key || win.pending.has(slot) || chain.failed.has(key)) continue;
		if (isLoaded(store, win.layer, slot) || !exists(tiles, win, slot)) continue;
		const tile = slotTile(placement, slot % WINDOW_TILES, Math.floor(slot / WINDOW_TILES));
		let dx = tile.x + 0.5 - cx;
		if (win.chart === MAP) dx -= columns * Math.round(dx / columns);
		queue.push({ slot, far: Math.hypot(dx, tile.y + 0.5 - cy) });
	}
	queue.sort((a, b) => a.far - b.far);

	for (const { slot } of queue) {
		if (chain.inflight >= MAX_INFLIGHT) return;
		const key = win.wanted[slot] as string;
		const sx = slot % WINDOW_TILES;
		const sy = Math.floor(slot / WINDOW_TILES);
		const tile = slotTile(placement, sx, sy);
		const abort = new AbortController();
		let timedOut = false;
		const timer = setTimeout(() => {
			timedOut = true;
			abort.abort();
		}, FETCH_TIMEOUT_S * 1000);
		win.pending.set(slot, { key, abort });
		chain.inflight++;
		const folder = CHART_FOLDER[win.chart];
		// A patch is built apart from its pyramid, and has its own cache token.
		// So have the tiles of the map that it is drawn over.
		const version =
			patchOf(tiles, win, tile)?.version ??
			(win.chart === MAP ? mapTileVersion(tiles, win.level, tile.x, tile.y) : tiles.version);
		const pyramid = { id: tiles.id, version };
		chain.kind
			.load(tileUrl(pyramid, folder, win.level, tile.x, tile.y, win.frame), abort.signal)
			.then((loaded) => {
				if (win.wanted[slot] === key && !abort.signal.aborted) {
					copyAt.set(sx * store.tileSize, (WINDOW_TILES - 1 - sy) * store.tileSize, win.layer);
					renderer.copyTextureToTexture(loaded.texture, store.texture, null, copyAt);
					setLoaded(store, win.layer, slot, true);
					chain.failures = 0;
					invalidate();
				}
				loaded.release();
			})
			.catch(() => {
				if (abort.signal.aborted && !timedOut) return;
				// The slot stays blank and the layer below shows through.
				chain.failed.add(key);
				if (++chain.failures >= MAX_FAILURES) chain.dead = true;
			})
			.finally(() => {
				clearTimeout(timer);
				chain.inflight--;
				if (win.pending.get(slot)?.key === key) win.pending.delete(slot);
			});
	}
}

function switchOff(chain: TileChain): void {
	for (const link of chain.uniforms.window.value) link.w = 0;
}

/** Free a chain's windows. Its uniforms stay, switched off. */
export function disposeChain(chain: TileChain): void {
	switchOff(chain);
	const store = chain.store;
	if (!store) return;
	for (const win of store.windows) for (const { abort } of win.pending.values()) abort.abort();
	store.texture.dispose();
	store.mask.dispose();
	chain.store = undefined;
	chain.uniforms.map.value = null;
	chain.uniforms.mask.value = null;
}

/** A frame that draws no window: free them once that has lasted. */
export function restChain(chain: TileChain, now: number): void {
	switchOff(chain);
	if (now - chain.lastUsed > IDLE_DISPOSE_S * 1000) disposeChain(chain);
}

const inverse = new Matrix4();
const over = new Vector3();
const anchor = new Vector3();

/** The point straight under the camera, as a direction in the frame of `mesh`. */
export function pointUnderCamera(mesh: Object3D, camera: PerspectiveCamera): Vector3 {
	return over
		.copy(camera.position)
		.applyMatrix4(inverse.copy(mesh.matrixWorld).invert())
		.normalize();
}

/** The finest level that has a tile near `over`, the point under the camera:
 *  past the pyramid's own where a window of the map reaches a patch. */
export function finestLevelAt(
	chain: TileChain | undefined,
	tiles: TilesBlock,
	over: Vector3
): number {
	if (cameraChart(over.y, chain?.chart) !== MAP) return tiles.max_level;
	const point = chartPoint(MAP, over.x, over.y, over.z);
	return deepestLevel(tiles.max_level, tiles.patches, point.x, point.y);
}

/** Windows a chain of `tiles` holds on a device that affords `limit`. One
 *  place more than the pyramid has levels, patches included: for the coarsest
 *  level on a second chart. */
export function chainLength(tiles: TilesBlock, limit: number): number {
	let finest = tiles.max_level;
	if (tiles.patches) for (const patch of tiles.patches) finest = Math.max(finest, patch.max_level);
	const levels = finest - FIRST_TILE_LEVEL + 1;
	return Math.min(limit, MAX_WINDOWS, levels + 1);
}

/**
 * Per-frame: keep the chain's windows on the ground under the camera. `over`
 * is the point straight under it, as a direction in the body's frame, and
 * `level` the level the screen needs there. `count` windows are held, and one
 * layer more for a window that changes chart. `radius` is that of the mesh, in
 * its own frame. `frame` is the month of a monthly map.
 */
export function updateChain(
	chain: TileChain,
	tiles: TilesBlock,
	count: number,
	level: number,
	over: Vector3,
	radius: number,
	frame: number | undefined,
	renderer: WebGLRenderer,
	invalidate: () => void
): void {
	chain.lastUsed = performance.now();
	const held = chain.store;
	if (held && (held.texture.image.depth !== count + 1 || held.kind !== chain.kind)) {
		disposeChain(chain);
	}
	const store = (chain.store ??= createStore(chain.kind, tiles.tile_size, count + 1, renderer));
	chain.uniforms.map.value = store.texture;
	chain.uniforms.mask.value = store.mask;
	chain.uniforms.filter.value.set(store.texture.anisotropy, tiles.tile_size);

	const cap = over.y >= 0 ? NORTH : SOUTH;
	chain.chart = cameraChart(over.y, chain.chart);
	const links = windowChain(level, count, chain.chart, over.y, tiles.max_level, chain.spread);
	// The same point near the mesh, with the digits the shader has: the place
	// of each window is counted from where the shader takes it to be.
	anchor.set(
		Math.fround(over.x * radius),
		Math.fround(over.y * radius),
		Math.fround(over.z * radius)
	);
	chain.uniforms.anchor.value.copy(anchor);
	const range = anchor.length();
	const home = chartPoint(MAP, anchor.x / range, anchor.y / range, anchor.z / range);

	const windowOf = (link: { chart: Chart; level: number }) =>
		store.windows.find((win) => win.chart === link.chart && win.level === link.level);

	// A window the chain dropped stays while the one that replaces it, the
	// same level on the chart the camera moved to, still loads.
	store.windows = store.windows.filter((win) => {
		win.rank = links.findIndex((link) => link.chart === win.chart && link.level === win.level);
		if (win.rank >= 0) return true;
		win.rank = links.length;
		const heir = links.find((link) => link.level === win.level);
		const heirWindow = heir && windowOf(heir);
		const near = win.chart === MAP || win.chart === cap;
		if (heir && near && !(heirWindow && settled(chain, store, tiles, heirWindow))) return true;
		release(store, win);
		return false;
	});

	// Coarsest first, to place and to load: it covers the most ground for the bytes.
	for (let i = links.length - 1; i >= 0; i--) {
		const link = links[i];
		let win = windowOf(link);
		if (!win) {
			const layer = store.free.pop();
			// Every layer is held: one frees when a window on its way out is replaced.
			if (layer === undefined) continue;
			win = { layer, ...link, rank: i, wanted: new Array(SLOTS), pending: new Map() };
			store.windows.push(win);
		}
		const point = chartPoint(link.chart, over.x, over.y, over.z);
		// Also on a new month: the keys carry the frame, so every slot reloads.
		retarget(
			store,
			win,
			placeWindow(link.chart, link.level, point.x, point.y, win.placement),
			frame
		);
		pump(chain, store, tiles, win, point.x, point.y, renderer, invalidate);
	}

	// Finest first; at one level the chain's window over the one it replaces.
	store.windows.sort((a, b) => b.level - a.level || a.rank - b.rank);
	for (let i = 0; i < MAX_DRAWN; i++) {
		const win = store.windows[i];
		const link = chain.uniforms.window.value[i];
		if (!win?.placement) {
			link.w = 0;
			continue;
		}
		chain.uniforms.grid.value[i].set(
			chartColumns(win.chart, win.level),
			chartRows(win.chart, win.level),
			win.placement.tx0,
			win.placement.ty0
		);
		if (win.chart === MAP) {
			const from = windowHome(win.placement, home.x, home.y);
			chain.uniforms.home.value[i].set(from.x, from.y);
		}
		link.set(win.chart, win.layer, win.level, 1);
		let loaded = 0;
		for (let slot = 0; slot < SLOTS; slot++) {
			if (isLoaded(store, win.layer, slot)) loaded |= 1 << slot;
		}
		chain.uniforms.loaded.value[i] = loaded;
	}
}
