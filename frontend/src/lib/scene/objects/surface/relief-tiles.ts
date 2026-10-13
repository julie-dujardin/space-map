import {
	DataTexture,
	type Material,
	NoColorSpace,
	type PerspectiveCamera,
	RGFormat,
	UnsignedByteType,
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
		uReliefLoaded: TileChain['uniforms']['loaded'];
		uReliefFilter: TileChain['uniforms']['filter'];
		/** Height range of the pyramid as a part of the body's radius. */
		uReliefScale: { value: number };
	};
}

const SLOPE_GLSL = /* glsl */ `
uniform sampler2DArray uReliefMap;
uniform sampler2DArray uReliefMask;
uniform vec4 uReliefGrid[ ${MAX_DRAWN} ];
uniform vec4 uReliefWindow[ ${MAX_DRAWN} ];
uniform int uReliefLoaded[ ${MAX_DRAWN} ];
uniform vec2 uReliefFilter;
uniform float uReliefScale;
${TILE_CHAIN_GLSL}
// Each byte is filtered alone, and the sum of the two is the filtered height.
float reliefValue( vec4 texel ) {
	return dot( texel.rg, vec2( 65280.0, 255.0 ) ) / 65535.0;
}

// How the coordinates of each chart change along the sphere at a direction:
// the dot product with a step along the sphere is that step on the chart.
struct ReliefRates {
	vec3 mapX;
	vec3 mapY;
	vec3 capX;
	vec3 capY;
};

ReliefRates reliefRates( vec3 dir, float side ) {
	ReliefRates rates;
	float flat2 = max( dir.x * dir.x + dir.z * dir.z, 1e-12 );
	rates.mapX = vec3( dir.z, 0.0, - dir.x ) / ( 2.0 * PI * flat2 );
	rates.mapY = ( dir * dir.y - vec3( 0.0, 1.0, 0.0 ) ) / ( PI * sqrt( flat2 ) );
	float fold = 1.0 + side * dir.y;
	float capScale = 0.5 / ( ${CAP_EDGE.toFixed(8)} * fold );
	vec2 plane = vec2( dir.x, side * dir.z ) * side / fold;
	rates.capX = vec3( 1.0, - plane.x, 0.0 ) * capScale;
	rates.capY = vec3( 0.0, - plane.y, side ) * capScale;
	rates.capX -= dir * dot( rates.capX, dir );
	rates.capY -= dir * dot( rates.capY, dir );
	return rates;
}

// Slope of the ground at a direction of the body's frame: a vector along the
// unit sphere that points uphill, as long as the rise over the run. Also
// gives the part of the fragment that the tiles answer for, and the finest
// window that does, or -1.
vec3 reliefTileSlope( vec3 dir, TileCharts charts, out float covered, out int first ) {
	covered = 0.0;
	first = - 1;
	vec3 slope = vec3( 0.0 );
	if ( uReliefWindow[ 0 ].w < 0.5 ) return slope;
	ReliefRates rates = reliefRates( dir, charts.side );

	float rows = ${WINDOW_TILES.toFixed(1)};
	for ( int i = 0; i < ${MAX_DRAWN}; i ++ ) {
		vec4 window = uReliefWindow[ i ];
		if ( window.w < 0.5 ) break;
		vec4 grid = uReliefGrid[ i ];
		vec2 spot;
		vec2 major;
		vec2 minor;
		float alpha = tileWindowWeight( charts, window, grid, - grid.zw, uReliefFilter, spot, major, minor );
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
		bool onMap = window.x < 0.5;
		vec3 uphill = rise.x * ( onMap ? rates.mapX : rates.capX ) + rise.y * ( onMap ? rates.mapY : rates.capY );
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
// sample.
struct ReliefSight {
	// The fragment in the window's texture, with its layer, and how far the
	// ray goes there in a radian.
	vec3 from;
	vec2 rate;
	// The part of the ray inside the window, in radians along it.
	float enters;
	float leaves;
	// The longest step that the window's pixels still hold.
	float widest;
	int loaded;
};

ReliefSight reliefSight( int i, TileCharts charts, vec2 mapStep, vec2 capStep ) {
	vec4 window = uReliefWindow[ i ];
	vec4 grid = uReliefGrid[ i ];
	bool onMap = window.x < 0.5;
	float rows = ${WINDOW_TILES.toFixed(1)};
	// In tiles from the window's north-west corner. The map goes round: the
	// fragment is taken on the side nearest the window.
	vec2 rel = ( onMap ? charts.mapAt : charts.capAt ) * grid.xy - grid.zw;
	if ( onMap ) rel.x = mod( rel.x - 0.5 * rows + 0.5 * grid.x, grid.x ) + 0.5 * rows - 0.5 * grid.x;
	vec2 rate = ( onMap ? mapStep : capStep ) * grid.xy;

	// Half a pixel in from the window's sides: past it the filter reads the
	// tile of the far side.
	float inset = 0.5 / uReliefFilter.y;
	vec2 run = mix( vec2( 1e-20 ), rate, greaterThan( abs( rate ), vec2( 1e-20 ) ) );
	vec2 a = ( inset - rel ) / run;
	vec2 b = ( rows - inset - rel ) / run;
	vec2 near = min( a, b );
	vec2 far = max( a, b );

	ReliefSight sight;
	sight.from = vec3( ( rel.x + grid.z ) / rows, - ( rel.y + grid.w ) / rows, window.y );
	sight.rate = vec2( rate.x, - rate.y ) / rows;
	sight.enters = max( near.x, near.y );
	sight.leaves = min( far.x, far.y );
	// The other pole's cap holds none of the ray.
	if ( ! onMap && ( window.x < 1.5 ) != ( charts.side > 0.0 ) ) sight.leaves = - 1.0;
	sight.widest = ${STEP_PIXELS.toFixed(2)} * PI / ( uReliefFilter.y * exp2( window.z ) );
	sight.loaded = uReliefLoaded[ i ];
	return sight;
}

// Height of the ground 't' radians along the ray, as a part of the pyramid's
// range. Negative where the window does not hold that ground.
float reliefSightValue( ReliefSight sight, float t ) {
	if ( t < sight.enters || t > sight.leaves ) return - 1.0;
	vec2 st = sight.from.xy + t * sight.rate;
	// Both tiles that the filter can read must be in.
	if ( sight.loaded != ${(1 << (WINDOW_TILES * WINDOW_TILES)) - 1} ) {
		vec2 tile = vec2( st.x, - st.y ) * ${WINDOW_TILES.toFixed(1)};
		float inset = 0.5 / uReliefFilter.y;
		ivec2 a = ivec2( floor( tile - inset ) ) & ${WINDOW_TILES - 1};
		ivec2 b = ivec2( floor( tile + inset ) ) & ${WINDOW_TILES - 1};
		int both = ( sight.loaded >> ( a.x + ${WINDOW_TILES} * a.y ) ) & ( sight.loaded >> ( b.x + ${WINDOW_TILES} * b.y ) );
		if ( ( both & 1 ) == 0 ) return - 1.0;
	}
	return reliefValue( textureLod( uReliefMap, vec3( st, sight.from.z ), 0.0 ) );
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
float reliefTileShadow( vec3 dir, TileCharts charts, vec3 toSun, float tanElev, float sunSize, int first ) {
	ReliefRates rates = reliefRates( dir, charts.side );
	vec2 mapStep = vec2( dot( rates.mapX, toSun ), dot( rates.mapY, toSun ) );
	vec2 capStep = vec2( dot( rates.capX, toSun ), dot( rates.capY, toSun ) );

	int drawn = 0;
	for ( int i = 0; i < ${MAX_DRAWN}; i ++ ) {
		if ( uReliefWindow[ i ].w > 0.5 ) drawn = i + 1;
	}
	int w = first;
	ReliefSight sight;
	float own = - 1.0;
	for ( int i = 0; i < ${MAX_DRAWN}; i ++ ) {
		if ( i < first ) continue;
		if ( i >= drawn ) break;
		w = i;
		sight = reliefSight( i, charts, mapStep, capStep );
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
	float pixel = sight.widest / ${STEP_PIXELS.toFixed(2)};
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
		if ( w + 1 < drawn && t - before > sight.widest ) {
			w ++;
			sight = reliefSight( w, charts, mapStep, capStep );
		}
		float value = reliefSightValue( sight, t );
		// The ray left this window, or a tile of it is missing.
		if ( value < 0.0 && w + 1 < drawn ) {
			w ++;
			sight = reliefSight( w, charts, mapStep, capStep );
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
		sight = reliefSight( w, charts, mapStep, capStep );
		for ( int k = 0; k < ${REFINE_STEPS}; k ++ ) {
			around *= 0.5;
			if ( w > start && around < sight.widest ) {
				w --;
				sight = reliefSight( w, charts, mapStep, capStep );
			}
			float centre = worst;
			for ( int e = 0; e < 2; e ++ ) {
				float at = centre + ( e == 0 ? - around : around );
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

async function loadTile(url: string, signal: AbortSignal): Promise<LoadedTile> {
	const { bytes, size } = await loadHeightTile(url, signal);
	const texture = new DataTexture(bytes, size, size, RGFormat, UnsignedByteType);
	return { texture, release: () => texture.dispose() };
}

/** Two bytes per pixel: half the memory of a colour window. */
const HEIGHT_TILES: TileKind = { format: RGFormat, colorSpace: NoColorSpace, load: loadTile };

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
	const chain = createChain(HEIGHT_TILES);
	const relief: ReliefTiles = {
		tiles,
		chain,
		shadowSteps: reliefShadowSteps(),
		uniforms: {
			uReliefMap: chain.uniforms.map,
			uReliefMask: chain.uniforms.mask,
			uReliefGrid: chain.uniforms.grid,
			uReliefWindow: chain.uniforms.window,
			uReliefLoaded: chain.uniforms.loaded,
			uReliefFilter: chain.uniforms.filter,
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
	const level =
		mesh && bo.selfShadow && !relief.chain.dead
			? neededLevel(bo.radiusScene, bo.cachedDist, projScale, relief.tiles.max_level)
			: -1;
	if (!mesh || level < FIRST_TILE_LEVEL) {
		restChain(relief.chain, performance.now());
		return;
	}
	const levels = relief.tiles.max_level - FIRST_TILE_LEVEL + 1;
	updateChain(
		relief.chain,
		relief.tiles,
		Math.min(maxReliefWindows(), levels),
		level,
		pointUnderCamera(mesh, camera),
		bo.radiusScene,
		undefined,
		renderer,
		invalidate
	);
}
