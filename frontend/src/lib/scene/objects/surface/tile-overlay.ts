import {
	DataArrayTexture,
	LinearFilter,
	LinearMipmapLinearFilter,
	Matrix4,
	type MeshStandardMaterial,
	NearestFilter,
	type PerspectiveCamera,
	RedFormat,
	RepeatWrapping,
	RGBAFormat,
	SRGBColorSpace,
	Texture,
	UnsignedByteType,
	Vector2,
	Vector3,
	Vector4,
	type WebGLRenderer
} from 'three';
import { tileUrl, tilesBase } from '$lib/fetch/data-base';
import { textureAllowed } from '$lib/host';
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
	neededLevel,
	placeWindow,
	slotTile,
	windowChain
} from '$lib/scene/lod/tile-window';
import { maxTileWindows } from '$lib/scene/render-tier';
import { chainShaderHook } from '$lib/scene/shaders/program-cache-key';
import type { BodyObjects, TilesBlock } from '$lib/scene/types';

/**
 * Surface tiles drawn over a body's whole-globe map while the camera is close.
 *
 * The map stays bound as it is. On top of it sits a chain of windows, each a
 * block of tiles around the point under the camera: the finest at the level
 * the screen needs there, each next one a level coarser and so twice as wide,
 * for the ground further out. A window has no mipmaps: the next one is its
 * mipmap. A fragment blends the two windows on either side of the level its
 * own footprint asks for, and takes the map where no window covers it or a
 * tile is missing, so a slow or unreachable tile host only costs detail.
 *
 * Near a pole the windows are on that pole's cap, where a tile is as wide on
 * the ground as it is tall. A window that changes chart loads on a spare
 * layer while the one it replaces stays drawn, so the change does not show.
 */

/** Windows the chain can hold. A device holds as many as its tier allows. */
const MAX_WINDOWS = 6;

/** Windows drawn at once: the chain, and one on its way out. */
const MAX_DRAWN = MAX_WINDOWS + 1;

/** Tile fetches in flight per body. */
const MAX_INFLIGHT = 6;

/** Failed fetches after which the pyramid is given up for the session: the
 *  host is down or does not carry it, and the tiers are the fallback. */
const MAX_FAILURES = 4;

/** Seconds a tile may take. A host that hangs, as a server on an absent
 *  network mount does, must count as failed like one that refuses. */
const FETCH_TIMEOUT_S = 30;

/** Seconds a body's windows outlive the last frame that needed them. */
const IDLE_DISPOSE_S = 5;

/** Width of the fade at a window's edge, in tiles. */
const FEATHER_TILES = 0.5;

/** Towards the horizon a pixel covers many more map pixels along the view
 *  than across it, and on the map also east-west by 1 / cos φ. */
const MAX_ANISOTROPY = 16;

const SLOTS = WINDOW_TILES * WINDOW_TILES;

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
	/** Every window, one layer each, and one layer to spare. */
	texture: DataArrayTexture;
	/** Per layer, a row of slots per tile row: 255 where the tile is in. */
	mask: DataArrayTexture;
	windows: TileWindow[];
	free: number[];
	tileSize: number;
}

export interface TileOverlay {
	material: MeshStandardMaterial;
	store?: WindowStore;
	uniforms: {
		uTileMap: { value: DataArrayTexture | null };
		uTileMask: { value: DataArrayTexture | null };
		/** Per window, finest first: columns and rows of its level, then its north-west tile. */
		uTileGrid: { value: Vector4[] };
		/** Per window: its chart, its layer, its level, and 1 while it is drawn. */
		uTileWindow: { value: Vector4[] };
		uTileFilter: { value: Vector2 };
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

const PARS = /* glsl */ `
varying vec3 vTileDir;
uniform sampler2DArray uTileMap;
uniform sampler2DArray uTileMask;
uniform vec4 uTileGrid[ ${MAX_DRAWN} ];
uniform vec4 uTileWindow[ ${MAX_DRAWN} ];
// Most taps of the anisotropic filter, and a tile's side in pixels.
uniform vec2 uTileFilter;

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

vec3 tileColour( vec3 below ) {
	if ( uTileWindow[ 0 ].w < 0.5 ) return below;

	// Where the fragment is on each chart, as fractions from the chart's
	// north-west corner, and what a screen pixel spans there. Both come from
	// the direction of the fragment rather than its interpolated coordinates:
	// those have one slope per triangle, which near a pole differs enough
	// between the two triangles of a grid cell to pick different levels, and
	// they jump at the 180° meridian.
	vec3 dir = normalize( vTileDir );
	vec3 ddx = dFdx( dir );
	vec3 ddy = dFdy( dir );

	float flat2 = max( dir.x * dir.x + dir.z * dir.z, 1e-12 );
	float east = 1.0 / ( 2.0 * PI * flat2 );
	float south = - 1.0 / ( PI * sqrt( flat2 ) );
	vec2 mapAt = vec2( fract( atan( dir.z, - dir.x ) / ( 2.0 * PI ) ), acos( clamp( dir.y, - 1.0, 1.0 ) ) / PI );
	vec2 mapDx = vec2( ( dir.z * ddx.x - dir.x * ddx.z ) * east, ddx.y * south );
	vec2 mapDy = vec2( ( dir.z * ddy.x - dir.x * ddy.z ) * east, ddy.y * south );

	// The cap of the fragment's own hemisphere, seen from above its pole.
	float side = dir.y < 0.0 ? - 1.0 : 1.0;
	float fold = 1.0 + side * dir.y;
	vec2 plane = vec2( dir.x, side * dir.z );
	float capScale = 0.5 / ( ${CAP_EDGE.toFixed(8)} * fold );
	vec2 capAt = 0.5 + plane * capScale;
	vec2 capDx = ( vec2( ddx.x, side * ddx.z ) - plane * ( side * ddx.y / fold ) ) * capScale;
	vec2 capDy = ( vec2( ddy.x, side * ddy.z ) - plane * ( side * ddy.y / fold ) ) * capScale;

	float rows = ${WINDOW_TILES.toFixed(1)};
	vec3 colour = vec3( 0.0 );
	float covered = 0.0;
	for ( int i = 0; i < ${MAX_DRAWN}; i ++ ) {
		vec4 window = uTileWindow[ i ];
		if ( window.w < 0.5 ) break;
		vec4 grid = uTileGrid[ i ];
		bool onMap = window.x < 0.5;
		// The other pole's cap.
		if ( ! onMap && ( window.x < 1.5 ) != ( side > 0.0 ) ) continue;
		vec2 tile = ( onMap ? mapAt : capAt ) * grid.xy;
		vec2 dx = ( onMap ? mapDx : capDx ) * grid.xy * uTileFilter.y;
		vec2 dy = ( onMap ? mapDy : capDy ) * grid.xy * uTileFilter.y;

		// Level this fragment asks of the window, from the short axis of its
		// footprint in the window's pixels: the long axis is the anisotropic
		// filter's to cover, as far as its taps reach. The window fades in
		// over the level below its own, as a mipmap would.
		vec2 major;
		vec2 minor;
		tileAxes( dx, dy, major, minor );
		float foot = max( length( minor ), length( major ) / uTileFilter.x );
		float weight = clamp( 1.0 - log2( max( foot, 1e-6 ) ), 0.0, 1.0 );
		if ( weight <= 0.0 ) continue;

		// Half a pixel in from a pole of the map: past it the filter would
		// read the far row.
		if ( onMap ) tile.y = clamp( tile.y, 0.0005, grid.y - 0.0005 );
		// Offset from the window's north-west corner; the map's longitude wraps.
		vec2 rel = tile - grid.zw;
		if ( onMap ) rel.x = mod( rel.x, grid.x );
		if ( rel.x < 0.0 || rel.x > rows || rel.y < 0.0 || rel.y > rows ) continue;
		// Distance to the window's edge, in tiles. A pole of the map is no
		// edge: nothing lies past it.
		vec2 near = min( rel, rows - rel );
		if ( onMap && grid.w < 0.5 ) near.y = rows - rel.y;
		if ( onMap && grid.w + rows > grid.y - 0.5 ) near.y = grid.w < 0.5 ? rows : rel.y;
		float edge = min( near.x, near.y );

		ivec3 slot = ivec3( int( mod( tile.x, rows ) ), int( mod( tile.y, rows ) ), int( window.y ) );
		float alpha = weight * texelFetch( uTileMask, slot, 0 ).r * smoothstep( 0.0, ${FEATHER_TILES.toFixed(2)}, edge );
		if ( alpha <= 0.0 ) continue;

		// The texture repeats every window: a tile sits in the slot its own
		// column and row pick, north up.
		vec3 st = vec3( tile.x / rows, - tile.y / rows, window.y );
		vec2 texel = vec2( 1.0, - 1.0 ) / ( rows * uTileFilter.y );
		colour += ( 1.0 - covered ) * alpha * textureGrad( uTileMap, st, major * texel, minor * texel ).rgb;
		covered += ( 1.0 - covered ) * alpha;
		if ( covered > 0.995 ) break;
	}
	return colour + ( 1.0 - covered ) * below;
}
`;

const MAP_FRAGMENT = /* glsl */ `
#ifdef USE_MAP
	vec4 sampledDiffuseColor = texture2D( map, vMapUv );
	sampledDiffuseColor.rgb = tileColour( sampledDiffuseColor.rgb );
	diffuseColor *= sampledDiffuseColor;
#endif
`;

function createOverlay(material: MeshStandardMaterial): TileOverlay {
	const overlay: TileOverlay = {
		material,
		uniforms: {
			uTileMap: { value: null },
			uTileMask: { value: null },
			uTileGrid: { value: Array.from({ length: MAX_DRAWN }, () => new Vector4()) },
			uTileWindow: { value: Array.from({ length: MAX_DRAWN }, () => new Vector4()) },
			uTileFilter: { value: new Vector2(1, 1) }
		},
		inflight: 0,
		failures: 0,
		failed: new Set(),
		dead: false,
		lastUsed: 0
	};
	chainShaderHook(material, 'surfaceTiles', (shader) => {
		Object.assign(shader.uniforms, overlay.uniforms);
		shader.vertexShader = shader.vertexShader
			.replace('#include <common>', '#include <common>\nvarying vec3 vTileDir;')
			.replace('#include <begin_vertex>', '#include <begin_vertex>\nvTileDir = position;');
		shader.fragmentShader = shader.fragmentShader
			.replace('#include <map_pars_fragment>', `#include <map_pars_fragment>\n${PARS}`)
			.replace('#include <map_fragment>', MAP_FRAGMENT);
	});
	return overlay;
}

function createStore(tileSize: number, layers: number, renderer: WebGLRenderer): WindowStore {
	const size = tileSize * WINDOW_TILES;
	const texture = new DataArrayTexture(null, size, size, layers);
	// Storage only: the tiles are copied in as they arrive.
	texture.source.dataReady = false;
	texture.format = RGBAFormat;
	texture.type = UnsignedByteType;
	texture.colorSpace = SRGBColorSpace;
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
	mask.minFilter = mask.magFilter = NearestFilter;
	mask.unpackAlignment = 1;
	mask.needsUpdate = true;

	const free = Array.from({ length: layers }, (_, layer) => layer);
	return { texture, mask, windows: [], free, tileSize };
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

/** Whether every tile of the window is in, or will not come. */
function settled(overlay: TileOverlay, store: WindowStore, win: TileWindow): boolean {
	for (let slot = 0; slot < SLOTS; slot++) {
		const key = win.wanted[slot];
		if (!key) return false;
		if (!isLoaded(store, win.layer, slot) && !overlay.failed.has(key)) return false;
	}
	return true;
}

async function fetchTile(url: string, signal: AbortSignal): Promise<ImageBitmap> {
	const response = await fetch(url, { signal });
	if (!response.ok) throw new Error(`tile ${response.status}`);
	// Flipped at decode: the window is stored north up, and a bitmap ignores
	// the upload's flip flag.
	return createImageBitmap(await response.blob(), {
		imageOrientation: 'flipY',
		premultiplyAlpha: 'none',
		colorSpaceConversion: 'none'
	});
}

const copyAt = new Vector3();
const queue: { slot: number; far: number }[] = [];

/** Start fetches for the blank slots of one window, those nearest the chart
 *  point `(x, y)` first. */
function pump(
	overlay: TileOverlay,
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
		if (!key || win.pending.has(slot) || overlay.failed.has(key)) continue;
		if (isLoaded(store, win.layer, slot)) continue;
		const tile = slotTile(placement, slot % WINDOW_TILES, Math.floor(slot / WINDOW_TILES));
		let dx = tile.x + 0.5 - cx;
		if (win.chart === MAP) dx -= columns * Math.round(dx / columns);
		queue.push({ slot, far: Math.hypot(dx, tile.y + 0.5 - cy) });
	}
	queue.sort((a, b) => a.far - b.far);

	for (const { slot } of queue) {
		if (overlay.inflight >= MAX_INFLIGHT) return;
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
		overlay.inflight++;
		const folder = CHART_FOLDER[win.chart];
		fetchTile(tileUrl(tiles, folder, win.level, tile.x, tile.y, win.frame), abort.signal)
			.then((bitmap) => {
				if (win.wanted[slot] === key && !abort.signal.aborted) {
					const source = new Texture(bitmap);
					source.colorSpace = SRGBColorSpace;
					source.flipY = false;
					source.generateMipmaps = false;
					copyAt.set(sx * store.tileSize, (WINDOW_TILES - 1 - sy) * store.tileSize, win.layer);
					renderer.copyTextureToTexture(source, store.texture, null, copyAt);
					source.dispose();
					setLoaded(store, win.layer, slot, true);
					overlay.failures = 0;
					invalidate();
				}
				bitmap.close();
			})
			.catch(() => {
				if (abort.signal.aborted && !timedOut) return;
				// The slot stays blank and the layer below shows through.
				overlay.failed.add(key);
				if (++overlay.failures >= MAX_FAILURES) overlay.dead = true;
			})
			.finally(() => {
				clearTimeout(timer);
				overlay.inflight--;
				if (win.pending.get(slot)?.key === key) win.pending.delete(slot);
			});
	}
}

function switchOff(overlay: TileOverlay): void {
	for (const link of overlay.uniforms.uTileWindow.value) link.w = 0;
}

/** A frame that draws no window: free them once that has lasted. */
function rest(bo: BodyObjects, overlay: TileOverlay, now: number): void {
	switchOff(overlay);
	if (now - overlay.lastUsed > IDLE_DISPOSE_S * 1000) disposeTileOverlay(bo);
}

/** Free a body's tile windows. The shader hook stays, switched off. */
export function disposeTileOverlay(bo: BodyObjects): void {
	const overlay = bo.tileOverlay;
	if (!overlay) return;
	switchOff(overlay);
	const store = overlay.store;
	if (!store) return;
	for (const win of store.windows) for (const { abort } of win.pending.values()) abort.abort();
	store.texture.dispose();
	store.mask.dispose();
	overlay.store = undefined;
	overlay.uniforms.uTileMap.value = null;
	overlay.uniforms.uTileMask.value = null;
}

/** Whether tiles carry this body's surface detail, so the largest whole-globe
 *  tier need not load. False once the tile host has failed it, and for a
 *  shape model, which takes the sphere's map and no windows. */
export function tilesServe(bo: BodyObjects): boolean {
	const tiles = bo.surfaceTiles;
	return (
		!!tiles &&
		!bo.model &&
		tiles.max_level >= FIRST_TILE_LEVEL &&
		tilesBase() !== '' &&
		maxTileWindows() > 0 &&
		!bo.tileOverlay?.dead &&
		textureAllowed(tiles.distribution)
	);
}

const inverse = new Matrix4();
const over = new Vector3();

/**
 * Per-frame: keep `bo`'s tile windows on the ground under the camera, at the
 * levels the screen needs. `projScale` is in device pixels. `drawable` is
 * false where the surface map must not be touched (hidden, replaced by a
 * host's picture).
 */
export function updateTileOverlay(
	bo: BodyObjects,
	camera: PerspectiveCamera,
	renderer: WebGLRenderer,
	projScale: number,
	drawable: boolean,
	invalidate: () => void
): void {
	const tiles = bo.surfaceTiles;
	const mesh = bo.mesh;
	const material = mesh?.material as MeshStandardMaterial | undefined;
	const level =
		tiles && mesh && material?.map && drawable && tilesServe(bo)
			? neededLevel(bo.radiusScene, bo.cachedDist, projScale, tiles.max_level)
			: -1;
	const now = performance.now();

	if (!tiles || !mesh || !material || level < FIRST_TILE_LEVEL) {
		if (bo.tileOverlay) rest(bo, bo.tileOverlay, now);
		return;
	}

	// A rebuilt mesh has a new material, without the hook.
	if (bo.tileOverlay && bo.tileOverlay.material !== material) {
		disposeTileOverlay(bo);
		bo.tileOverlay = undefined;
	}
	const overlay = (bo.tileOverlay ??= createOverlay(material));
	overlay.lastUsed = now;

	// One place more than the pyramid has levels: for the coarsest level on a
	// second chart. One layer more than that: for a window changing chart.
	const levels = tiles.max_level - FIRST_TILE_LEVEL + 1;
	const count = Math.min(maxTileWindows(), MAX_WINDOWS, levels + 1);
	if (overlay.store && overlay.store.texture.image.depth !== count + 1) disposeTileOverlay(bo);
	const store = (overlay.store ??= createStore(tiles.tile_size, count + 1, renderer));
	overlay.uniforms.uTileMap.value = store.texture;
	overlay.uniforms.uTileMask.value = store.mask;
	overlay.uniforms.uTileFilter.value.set(store.texture.anisotropy, tiles.tile_size);

	// The point straight under the camera, as a direction in the body's frame.
	over.copy(camera.position).applyMatrix4(inverse.copy(mesh.matrixWorld).invert()).normalize();
	const cap = over.y >= 0 ? NORTH : SOUTH;
	overlay.chart = cameraChart(over.y, overlay.chart);
	const chain = windowChain(level, count, overlay.chart, over.y);
	// Also on a new month: the keys carry the frame, so every slot reloads.
	const frame = tiles.frames ? bo.textureFrame : undefined;

	const held = (link: { chart: Chart; level: number }) =>
		store.windows.find((win) => win.chart === link.chart && win.level === link.level);

	// A window the chain dropped stays while the one that replaces it, the
	// same level on the chart the camera moved to, still loads.
	store.windows = store.windows.filter((win) => {
		win.rank = chain.findIndex((link) => link.chart === win.chart && link.level === win.level);
		if (win.rank >= 0) return true;
		win.rank = chain.length;
		const heir = chain.find((link) => link.level === win.level);
		const heirWindow = heir && held(heir);
		const near = win.chart === MAP || win.chart === cap;
		if (heir && near && !(heirWindow && settled(overlay, store, heirWindow))) return true;
		release(store, win);
		return false;
	});

	// Coarsest first, to place and to load: it covers the most ground for the bytes.
	for (let i = chain.length - 1; i >= 0; i--) {
		const link = chain[i];
		let win = held(link);
		if (!win) {
			const layer = store.free.pop();
			// Every layer is held: one frees when a window on its way out is replaced.
			if (layer === undefined) continue;
			win = { layer, ...link, rank: i, wanted: new Array(SLOTS), pending: new Map() };
			store.windows.push(win);
		}
		const point = chartPoint(link.chart, over.x, over.y, over.z);
		retarget(
			store,
			win,
			placeWindow(link.chart, link.level, point.x, point.y, win.placement),
			frame
		);
		pump(overlay, store, tiles, win, point.x, point.y, renderer, invalidate);
	}

	// Finest first; at one level the chain's window over the one it replaces.
	store.windows.sort((a, b) => b.level - a.level || a.rank - b.rank);
	for (let i = 0; i < MAX_DRAWN; i++) {
		const win = store.windows[i];
		const link = overlay.uniforms.uTileWindow.value[i];
		if (!win?.placement) {
			link.w = 0;
			continue;
		}
		overlay.uniforms.uTileGrid.value[i].set(
			chartColumns(win.chart, win.level),
			chartRows(win.chart, win.level),
			win.placement.tx0,
			win.placement.ty0
		);
		link.set(win.chart, win.layer, win.level, 1);
	}
}
