import {
	DataTexture,
	FloatType,
	type Material,
	NoColorSpace,
	type PerspectiveCamera,
	RedFormat,
	RGFormat,
	UnsignedByteType,
	Vector4,
	type WebGLRenderer
} from 'three';
import { tilesBase } from '$lib/fetch/data-base';
import { textureAllowed } from '$lib/host';
import { CAP_EDGE, FIRST_TILE_LEVEL, WINDOW_TILES, neededLevel } from '$lib/scene/lod/tile-window';
import { loadHeightTile } from '$lib/scene/relief/client';
import { maxReliefWindows, reliefShadowSteps } from '$lib/scene/render-tier';
import type { BodyObjects, TilesBlock } from '$lib/scene/types';
import {
	MAX_DRAWN,
	TILE_CHAIN_GLSL,
	type LoadedTile,
	type TileChain,
	type TileKind,
	createChain,
	disposeChain,
	finestLevelAt,
	pointUnderCamera,
	restChain,
	updateChain
} from './tile-chain';

/**
 * A body's height tiles, as the slope of the ground under each pixel and the
 * shadows that the ground casts on it.
 *
 * The whole-globe height map stays bound, for the far ground. Close up, a
 * chain of tile windows (see `tile-chain.ts`) gives both at the full detail of
 * the pyramid, in 16 bits. The code here is one part of the self-shadow
 * shader. The terrain grid takes its heights from the same tiles (see
 * `terrain-window.ts`).
 *
 * Near a patch the chain goes past the pyramid's finest level. The tiles of a
 * patch state a height to 1/256 of a 16-bit step, and the windows hold each
 * height as one number from the first time the chain goes that deep.
 */

/** Longest shadow ray, in heights of the pyramid's range. A ray is cut short
 *  where it clears that range. */
const MARCH_REACH = 8;

/** A ray reads the next window once its step is this many of a window's
 *  pixels: the coarser pixels hold what lies between two samples. */
const STEP_PIXELS = 1.5;

/** Halvings of the step around the sample that hides the most. */
const REFINE_STEPS = 3;

/** Steepest ground that the search around a sample allows for: a crest
 *  beside the sample stands higher by at most this slope over half a step. */
const STEEPEST = 1;

/** Least radius of the Sun's disc for the edge of a shadow, in radians. The
 *  samples of a ray miss the true crest by a part of their step, and a
 *  sharper edge would show that. */
const MIN_SUN_SIZE = 0.006;

export interface ReliefTiles {
	tiles: TilesBlock;
	chain: TileChain;
	/** Samples of a shadow ray in the shader as it was last asked for. */
	shadowSteps: number;
	uniforms: {
		uReliefMap: TileChain['uniforms']['map'];
		uReliefMask: TileChain['uniforms']['mask'];
		uReliefGrid: TileChain['uniforms']['grid'];
		uReliefWindow: TileChain['uniforms']['window'];
		uReliefHome: TileChain['uniforms']['home'];
		uReliefAnchor: TileChain['uniforms']['anchor'];
		uReliefLoaded: TileChain['uniforms']['loaded'];
		uReliefFilter: TileChain['uniforms']['filter'];
		/** What a pixel of the windows is multiplied by: see `reliefValue`. */
		uReliefRead: { value: Vector4 };
		/** Height range of the pyramid as a part of the body's radius. */
		uReliefScale: { value: number };
	};
}

const SLOPE_GLSL = /* glsl */ `
uniform sampler2DArray uReliefMap;
uniform sampler2DArray uReliefMask;
uniform vec4 uReliefGrid[ ${MAX_DRAWN} ];
uniform vec4 uReliefWindow[ ${MAX_DRAWN} ];
uniform vec2 uReliefHome[ ${MAX_DRAWN} ];
uniform vec3 uReliefAnchor;
uniform int uReliefLoaded[ ${MAX_DRAWN} ];
uniform vec2 uReliefFilter;
uniform vec4 uReliefRead;
uniform float uReliefScale;
varying vec3 vReliefOff;
${TILE_CHAIN_GLSL}
// The height of a pixel of the windows, as a part of the pyramid's range.
// They hold it as two bytes or as one number, and uReliefRead weighs either.
float reliefValue( vec4 texel ) {
	return dot( texel, uReliefRead );
}

// How the coordinates of each chart change along the sphere at a direction,
// as a mat2x3 per chart: a step along the sphere times it is that step on the
// chart, and it times a step on the chart is that step along the sphere.
void reliefRates( vec3 dir, float side, out mat2x3 map, out mat2x3 cap ) {
	float flat2 = max( dir.x * dir.x + dir.z * dir.z, 1e-12 );
	map = mat2x3(
		vec3( dir.z, 0.0, - dir.x ) / ( 2.0 * PI * flat2 ),
		( dir * dir.y - vec3( 0.0, 1.0, 0.0 ) ) / ( PI * sqrt( flat2 ) )
	);
	float fold = 1.0 + side * dir.y;
	float capScale = 0.5 / ( ${CAP_EDGE.toFixed(8)} * fold );
	vec2 plane = vec2( dir.x, side * dir.z ) * side / fold;
	vec3 capX = vec3( 1.0, - plane.x, 0.0 ) * capScale;
	vec3 capY = vec3( 0.0, - plane.y, side ) * capScale;
	cap = mat2x3( capX - dir * dot( capX, dir ), capY - dir * dot( capY, dir ) );
}

// Slope of the ground at a direction of the body's frame: a vector along the
// unit sphere that points uphill, as long as the rise over the run. Also
// gives the part of the fragment that the tiles answer for, and the finest
// window that does, or -1.
vec3 reliefTileSlope( vec3 dir, mat3x2 map, mat3x2 cap, float side, out float covered, out int first ) {
	covered = 0.0;
	first = - 1;
	vec3 slope = vec3( 0.0 );
	if ( uReliefWindow[ 0 ].w < 0.5 ) return slope;
	mat2x3 mapRates;
	mat2x3 capRates;
	reliefRates( dir, side, mapRates, capRates );

	float rows = ${WINDOW_TILES.toFixed(1)};
	for ( int i = 0; i < ${MAX_DRAWN}; i ++ ) {
		vec4 window = uReliefWindow[ i ];
		if ( window.w < 0.5 ) break;
		vec4 grid = uReliefGrid[ i ];
		vec2 spot;
		vec2 major;
		vec2 minor;
		float alpha = tileWindowWeight( map, cap, side, window, grid, uReliefHome[ i ], uReliefFilter, spot, major, minor );
		if ( alpha <= 0.0 ) continue;
		// Filtered, the mask falls towards a missing tile. The pixels beside
		// one are left out: their slope would read its blank slot.
		alpha *= smoothstep( 0.51, 0.55, texture( uReliefMask, vec3( spot / rows, window.y ) ).r );
		if ( alpha <= 0.0 ) continue;
		if ( first < 0 ) first = i;

		vec3 st = vec3( spot.x / rows, - spot.y / rows, window.y );
		vec2 texel = vec2( 1.0, - 1.0 ) / ( rows * uReliefFilter.y );
		vec2 gx = major * texel;
		vec2 gy = minor * texel;
		vec3 east = vec3( texel.x, 0.0, 0.0 );
		vec3 south = vec3( 0.0, texel.y, 0.0 );
		// Rise over two pixels of the window, then over the whole chart.
		vec2 rise = vec2(
			reliefValue( textureGrad( uReliefMap, st + east, gx, gy ) ) - reliefValue( textureGrad( uReliefMap, st - east, gx, gy ) ),
			reliefValue( textureGrad( uReliefMap, st + south, gx, gy ) ) - reliefValue( textureGrad( uReliefMap, st - south, gx, gy ) )
		) * 0.5 * grid.xy * uReliefFilter.y;
		vec3 uphill = ( window.x < 0.5 ? mapRates : capRates ) * rise;
		slope += ( 1.0 - covered ) * alpha * uphill;
		covered += ( 1.0 - covered ) * alpha;
		if ( covered > 0.995 ) break;
	}
	return slope * uReliefScale;
}
`;

/**
 * The shadow part of the shader: `reliefTileShadow`, whose ray takes `steps`
 * samples. The count is a constant of the shader: as a uniform it costs a
 * weak GPU much more for each sample.
 */
function shadowGlsl(steps: number): string {
	return /* glsl */ `
// One window as a shadow ray reads it. The ray is a line on the window's
// chart, so where it is inside the window is worked out once, not at each
// sample. 'sight' holds what a sample reads, as a mat2x4 and not a struct
// (see the chain code): the fragment's place in the window's texture and how
// far the ray goes there in a radian; then the part of the ray inside the
// window, in radians along it, the window's layer and its tiles that are in,
// a bit each. 'widest' is the longest step that the window's pixels still
// hold, 'hands' the step from which the ray reads the next window, and
// 'beyond' how far from the fragment the next window can be read at all.
void reliefSight( int i, mat3x2 map, mat3x2 cap, float side, vec2 mapStep, vec2 capStep, out mat2x4 sight, out float widest, out float hands, out float beyond ) {
	vec4 window = uReliefWindow[ i ];
	vec4 grid = uReliefGrid[ i ];
	bool onMap = window.x < 0.5;
	float rows = ${WINDOW_TILES.toFixed(1)};
	// In tiles from the window's north-west corner. The map is counted from
	// the point under the camera, so the fragment is on the side of the globe
	// nearest the window.
	vec2 rel = onMap ? uReliefHome[ i ] + map[ 0 ] * grid.xy : cap[ 0 ] * grid.xy - grid.zw;
	vec2 rate = ( onMap ? mapStep : capStep ) * grid.xy;

	// Half a pixel in from the window's sides: past it the filter reads the
	// tile of the far side.
	float inset = 0.5 / uReliefFilter.y;
	vec2 run = mix( vec2( 1e-20 ), rate, greaterThan( abs( rate ), vec2( 1e-20 ) ) );
	vec2 a = ( inset - rel ) / run;
	vec2 b = ( rows - inset - rel ) / run;
	vec2 near = min( a, b );
	vec2 far = max( a, b );

	// The texture repeats every window. The tile index of a patch alone takes
	// all the digits of a float: only its place in the window is added.
	vec2 slot = rel + mod( grid.zw, rows );
	float leaves = min( far.x, far.y );
	// The other pole's cap holds none of the ray.
	if ( ! onMap && ( window.x < 1.5 ) != ( side > 0.0 ) ) leaves = - 1.0;
	sight = mat2x4(
		slot.x / rows, - slot.y / rows, rate.x / rows, - rate.y / rows,
		max( near.x, near.y ), leaves, window.y, float( uReliefLoaded[ i ] )
	);
	widest = ${STEP_PIXELS.toFixed(2)} * PI / ( uReliefFilter.y * exp2( window.z ) );
	// Near a patch the next window can be some levels coarser. The ray then
	// stays here until its step is half of what that window holds: too wide
	// for these pixels, but they are the same ground as the fragment's. The
	// pyramid around a patch is not: it has none of the hills that only the
	// patch resolves, and close to the fragment it would stand in the ray.
	hands = widest;
	beyond = 0.0;
	if ( i + 1 < ${MAX_DRAWN} ) {
		float next = PI / ( uReliefFilter.y * exp2( uReliefWindow[ i + 1 ].z ) );
		hands = max( hands, 0.5 * ${STEP_PIXELS.toFixed(2)} * next );
		// Within half a pixel of a window, its height is that of the fragment's
		// own pixel, and the fragment stands above or below that by all the
		// relief that the pixel averages away.
		beyond = 0.5 * next;
	}
}

// Height of the ground 't' radians along the ray, as a part of the pyramid's
// range. Negative where the window does not hold that ground.
float reliefSightValue( mat2x4 sight, float t ) {
	if ( t < sight[ 1 ].x || t > sight[ 1 ].y ) return - 1.0;
	vec2 st = sight[ 0 ].xy + t * sight[ 0 ].zw;
	// Both tiles that the filter can read must be in.
	if ( sight[ 1 ].w != ${((1 << (WINDOW_TILES * WINDOW_TILES)) - 1).toFixed(1)} ) {
		int loaded = int( sight[ 1 ].w );
		vec2 tile = vec2( st.x, - st.y ) * ${WINDOW_TILES.toFixed(1)};
		float inset = 0.5 / uReliefFilter.y;
		ivec2 a = ivec2( floor( tile - inset ) ) & ${WINDOW_TILES - 1};
		ivec2 b = ivec2( floor( tile + inset ) ) & ${WINDOW_TILES - 1};
		int both = ( loaded >> ( a.x + ${WINDOW_TILES} * a.y ) ) & ( loaded >> ( b.x + ${WINDOW_TILES} * b.y ) );
		if ( ( both & 1 ) == 0 ) return - 1.0;
	}
	return reliefValue( textureLod( uReliefMap, vec3( st, sight[ 1 ].z ), 0.0 ) );
}

// Part of the Sun's disc that the ground leaves in sight of the fragment at
// 'dir', or -1 where no window holds the fragment. The Sun is 'toSun' along
// the sphere, 'tanElev' above it, and 'sunSize' is the radius of its disc.
// 'first' is the fragment's window, as the slope gave it.
//
// A ray is marched towards the Sun. Each step is longer than the last by one
// ratio, from a pixel of the fragment's window to the end of the ray, and is
// read from the window whose pixels are about as wide as the step. A shadow
// is then sharp beside what casts it, at a cost that does not grow with its
// length.
float reliefTileShadow( vec3 dir, mat3x2 map, mat3x2 cap, float side, vec3 toSun, float tanElev, float sunSize, int first ) {
	mat2x3 mapRates;
	mat2x3 capRates;
	reliefRates( dir, side, mapRates, capRates );
	vec2 mapStep = toSun * mapRates;
	vec2 capStep = toSun * capRates;

	int drawn = 0;
	for ( int i = 0; i < ${MAX_DRAWN}; i ++ ) {
		if ( uReliefWindow[ i ].w > 0.5 ) drawn = i + 1;
	}
	int w = first;
	mat2x4 sight;
	float widest;
	float hands;
	float beyond;
	float own = - 1.0;
	for ( int i = 0; i < ${MAX_DRAWN}; i ++ ) {
		if ( i < first ) continue;
		if ( i >= drawn ) break;
		w = i;
		reliefSight( i, map, cap, side, mapStep, capStep, sight, widest, hands, beyond );
		own = reliefSightValue( sight, 0.0 );
		if ( own >= 0.0 ) break;
	}
	if ( own < 0.0 ) return - 1.0;
	int start = w;

	// A ray rises above the sphere by its slope, and by the sphere's own
	// curve under it. Past where it clears the pyramid's range, nothing
	// can stand in it.
	float clear = sqrt( tanElev * tanElev + 2.0 * uReliefScale * ( 1.0 - own ) ) - tanElev;
	float reach = min( clear, ${MARCH_REACH.toFixed(1)} * uReliefScale );
	if ( reach < 1e-7 ) return 1.0;

	// The ratio that takes steps from one pixel to the reach: 'rate' is its
	// logarithm times the count, and solves rate / ( exp( rate ) - 1 ) = part.
	float count = ${steps.toFixed(1)};
	float pixel = widest / ${STEP_PIXELS.toFixed(2)};
	float part = count * pixel / reach;
	float rate = 0.0;
	if ( part < 1.0 ) {
		rate = - log( part );
		for ( int k = 0; k < 4; k ++ ) rate = log( 1.0 + rate / part );
	}
	// Each sample is the one before times the ratio, plus the first step.
	bool even = rate < 1e-3;
	float ratio = even ? 1.0 : exp( rate / count );
	float head = even ? reach / count : reach * ( ratio - 1.0 ) / ( exp( rate ) - 1.0 );

	// How far the ground stands into the ray is counted in discs of the Sun.
	// The disc is an angle, and the ray's rise is a slope.
	float perDisc = 1.0 / ( max( sunSize, ${MIN_SUN_SIZE.toFixed(4)} ) * ( 1.0 + tanElev * tanElev ) );
	float t = 0.0;
	float hidden = - 1e9;
	// The sample that hides the most, the step around it and its window.
	float worst = 0.0;
	float around = 0.0;
	int worstWindow = w;
	for ( int i = 1; i <= ${steps}; i ++ ) {
		float before = t;
		t = t * ratio + head;
		if ( w + 1 < drawn && t - before > hands ) {
			w ++;
			reliefSight( w, map, cap, side, mapStep, capStep, sight, widest, hands, beyond );
		}
		float value = reliefSightValue( sight, t );
		// The ray left this window, or a tile of it is missing.
		if ( value < 0.0 && w + 1 < drawn ) {
			if ( t < beyond ) continue;
			w ++;
			reliefSight( w, map, cap, side, mapStep, capStep, sight, widest, hands, beyond );
			value = reliefSightValue( sight, t );
		}
		if ( value < 0.0 ) continue;
		float stands = ( ( value - own ) * uReliefScale / t - tanElev - 0.5 * t ) * perDisc;
		if ( stands > hidden ) {
			hidden = stands;
			worst = t;
			around = t - before;
			worstWindow = w;
			// The whole disc is hidden.
			if ( hidden >= 1.0 ) break;
		}
	}

	// The crest that hides the most lies between two samples, and far out
	// those are far apart. Look for it around the best one, each time at half
	// the distance and in a finer window. Not where the best one is so clear
	// of the ray that no crest beside it can reach the Sun's disc.
	float crest = ${(STEEPEST * 0.5).toFixed(2)} * around / max( worst, 1e-9 ) * perDisc;
	if ( hidden < 1.0 && hidden + crest > - 1.0 ) {
		w = worstWindow;
		reliefSight( w, map, cap, side, mapStep, capStep, sight, widest, hands, beyond );
		for ( int k = 0; k < ${REFINE_STEPS}; k ++ ) {
			around *= 0.5;
			if ( w > start && around < widest ) {
				w --;
				reliefSight( w, map, cap, side, mapStep, capStep, sight, widest, hands, beyond );
			}
			float centre = worst;
			for ( int e = 0; e < 2; e ++ ) {
				float at = centre + ( e == 0 ? - around : around );
				// Nearer than a pixel, the window holds no crest: only the slope
				// of the fragment's own ground, which is the normal's to light.
				if ( at < widest * ${(1 / STEP_PIXELS).toFixed(4)} ) continue;
				float value = reliefSightValue( sight, at );
				if ( value < 0.0 ) continue;
				float stands = ( ( value - own ) * uReliefScale / at - tanElev - 0.5 * at ) * perDisc;
				if ( stands > hidden ) {
					hidden = stands;
					worst = at;
				}
			}
		}
	}
	return 1.0 - smoothstep( - 1.0, 1.0, hidden );
}
`;
}

/** Declarations and `reliefTileSlope`, for a fragment shader that has `PI`.
 *  With `steps` above zero, `reliefTileShadow` too. */
export function reliefTilesGlsl(steps: number): string {
	return steps > 0 ? SLOPE_GLSL + shadowGlsl(steps) : SLOPE_GLSL;
}

function heightTiles(fine: boolean): TileKind {
	const format = fine ? RedFormat : RGFormat;
	const type = fine ? FloatType : UnsignedByteType;
	return {
		format,
		type,
		colorSpace: NoColorSpace,
		async load(url, signal): Promise<LoadedTile> {
			const tile = await loadHeightTile(url, fine, signal);
			const texture = new DataTexture(tile.heights, tile.size, tile.size, format, type);
			return { texture, release: () => texture.dispose() };
		}
	};
}

/** Two bytes per pixel: half the memory of a colour window. */
const HEIGHT_TILES = heightTiles(false);
const BYTES_READ = new Vector4(65280 / 65535, 255 / 65535, 0, 0);

/**
 * One number per pixel, as much memory as a colour window. A GPU filters each
 * byte to 1/256, so where the high byte differs between two pixels the sum of
 * the bytes is off by up to half a step. That is nothing across a pixel of
 * the pyramid, and a steep slope across the metre of a pixel of a patch.
 */
const FINE_HEIGHT_TILES = heightTiles(true);
const NUMBER_READ = new Vector4(1 / 65535, 0, 0, 0);

/** Whether this host and device can draw the height pyramid `tiles` at all. */
export function reliefTilesAvailable(tiles: TilesBlock | undefined): tiles is TilesBlock {
	return (
		!!tiles &&
		tiles.scale_km !== undefined &&
		tiles.max_level >= FIRST_TILE_LEVEL &&
		tilesBase() !== '' &&
		maxReliefWindows() > 0 &&
		textureAllowed(tiles.distribution)
	);
}

/**
 * The windows of the height pyramid `tiles` on `material`, for a body of
 * `radiusKm`; none where the pyramid cannot be drawn. A material keeps one
 * set: its compiled shader reads their uniforms.
 */
export function reliefTilesOf(
	material: Material,
	tiles: TilesBlock | undefined,
	radiusKm: number
): ReliefTiles | undefined {
	if (!reliefTilesAvailable(tiles)) return undefined;
	const held = material.userData.reliefTiles as ReliefTiles | undefined;
	if (held) return held;
	const chain = createChain(HEIGHT_TILES, true);
	const relief: ReliefTiles = {
		tiles,
		chain,
		shadowSteps: reliefShadowSteps(),
		uniforms: {
			uReliefMap: chain.uniforms.map,
			uReliefMask: chain.uniforms.mask,
			uReliefGrid: chain.uniforms.grid,
			uReliefWindow: chain.uniforms.window,
			uReliefHome: chain.uniforms.home,
			uReliefAnchor: chain.uniforms.anchor,
			uReliefLoaded: chain.uniforms.loaded,
			uReliefFilter: chain.uniforms.filter,
			uReliefRead: { value: BYTES_READ },
			uReliefScale: { value: (tiles.scale_km ?? 0) / radiusKm }
		}
	};
	material.userData.reliefTiles = relief;
	return relief;
}

/** Whether tiles carry this body's relief up close, so the largest
 *  whole-globe height tier need not load. False once the tile host has
 *  failed the pyramid. */
export function reliefTilesServe(bo: BodyObjects): boolean {
	return !!bo.reliefTiles && !bo.reliefTiles.chain.dead;
}

/** Free a body's height windows. Its shader keeps the uniforms, switched off. */
export function disposeReliefTiles(bo: BodyObjects): void {
	if (bo.reliefTiles) disposeChain(bo.reliefTiles.chain);
}

/**
 * Per-frame: keep `bo`'s height windows on the ground under the camera, at
 * the levels the screen needs. `projScale` is in device pixels.
 */
export function updateReliefTiles(
	bo: BodyObjects,
	camera: PerspectiveCamera,
	renderer: WebGLRenderer,
	projScale: number,
	invalidate: () => void
): void {
	const relief = bo.reliefTiles;
	if (!relief) return;
	const mesh = bo.mesh;
	// The count is in the shader's text: another one is another shader.
	if (mesh && relief.shadowSteps !== reliefShadowSteps()) {
		relief.shadowSteps = reliefShadowSteps();
		(mesh.material as Material).needsUpdate = true;
	}
	const { chain, tiles } = relief;
	const over = mesh && bo.selfShadow && !chain.dead ? pointUnderCamera(mesh, camera) : undefined;
	// A device that cannot filter a window of numbers stays on the pyramid.
	const deep = renderer.extensions.has('OES_texture_float_linear');
	const level = over
		? neededLevel(
				bo.radiusScene,
				bo.cachedDist,
				projScale,
				deep ? finestLevelAt(chain, tiles, over) : tiles.max_level
			)
		: -1;
	if (!over || level < FIRST_TILE_LEVEL) {
		restChain(chain, performance.now());
		// The next windows are of bytes again, until a patch asks for more.
		if (!chain.store) chain.kind = HEIGHT_TILES;
		return;
	}
	// Kept from then on: a change of kind loads every window again.
	if (level > tiles.max_level) chain.kind = FINE_HEIGHT_TILES;
	let finest = tiles.max_level;
	if (deep) for (const patch of tiles.patches ?? []) finest = Math.max(finest, patch.max_level);
	updateChain(
		chain,
		tiles,
		Math.min(maxReliefWindows(), finest - FIRST_TILE_LEVEL + 1),
		level,
		over,
		bo.radiusScene,
		undefined,
		renderer,
		invalidate
	);
	relief.uniforms.uReliefRead.value = chain.kind === FINE_HEIGHT_TILES ? NUMBER_READ : BYTES_READ;
}
