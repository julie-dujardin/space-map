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
import { maxReliefWindows } from '$lib/scene/render-tier';
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
 * A body's height tiles, as the slope of the ground under each pixel.
 *
 * The whole-globe height map stays bound: it casts the shadows and gives the
 * slope of the far ground. Close up, a chain of tile windows (see
 * `tile-chain.ts`) gives the slope at the full detail of the pyramid, in 16
 * bits. The code here is one part of the self-shadow shader. The terrain grid
 * takes its heights from the same tiles (see `terrain-window.ts`).
 */

export interface ReliefTiles {
	tiles: TilesBlock;
	chain: TileChain;
	uniforms: {
		uReliefMap: TileChain['uniforms']['map'];
		uReliefMask: TileChain['uniforms']['mask'];
		uReliefGrid: TileChain['uniforms']['grid'];
		uReliefWindow: TileChain['uniforms']['window'];
		uReliefFilter: TileChain['uniforms']['filter'];
		/** Height range of the pyramid as a part of the body's radius. */
		uReliefScale: { value: number };
	};
}

/** Declarations and `reliefTileSlope`, for a fragment shader that has `PI`. */
export const RELIEF_TILES_GLSL = /* glsl */ `
uniform sampler2DArray uReliefMap;
uniform sampler2DArray uReliefMask;
uniform vec4 uReliefGrid[ ${MAX_DRAWN} ];
uniform vec4 uReliefWindow[ ${MAX_DRAWN} ];
uniform vec2 uReliefFilter;
uniform float uReliefScale;
${TILE_CHAIN_GLSL}
// Each byte is filtered alone, and the sum of the two is the filtered height.
float reliefHeight( vec3 st, vec2 gx, vec2 gy ) {
	return dot( textureGrad( uReliefMap, st, gx, gy ).rg, vec2( 65280.0, 255.0 ) ) / 65535.0;
}

// Slope of the ground at a direction of the body's frame: a vector along the
// unit sphere that points uphill, as long as the rise over the run. The
// second value is the part of the fragment that the tiles answer for.
vec3 reliefTileSlope( vec3 dir, out float covered ) {
	covered = 0.0;
	vec3 slope = vec3( 0.0 );
	if ( uReliefWindow[ 0 ].w < 0.5 ) return slope;
	TileCharts charts = tileCharts( dir );

	// How each chart's coordinates change along the sphere.
	float flat2 = max( dir.x * dir.x + dir.z * dir.z, 1e-12 );
	vec3 mapX = vec3( dir.z, 0.0, - dir.x ) / ( 2.0 * PI * flat2 );
	vec3 mapY = ( dir * dir.y - vec3( 0.0, 1.0, 0.0 ) ) / ( PI * sqrt( flat2 ) );
	float fold = 1.0 + charts.side * dir.y;
	float capScale = 0.5 / ( ${CAP_EDGE.toFixed(8)} * fold );
	vec2 plane = vec2( dir.x, charts.side * dir.z ) * charts.side / fold;
	vec3 capX = vec3( 1.0, - plane.x, 0.0 ) * capScale;
	vec3 capY = vec3( 0.0, - plane.y, charts.side ) * capScale;
	capX -= dir * dot( capX, dir );
	capY -= dir * dot( capY, dir );

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

		vec3 st = vec3( spot.x / rows, - spot.y / rows, window.y );
		vec2 texel = vec2( 1.0, - 1.0 ) / ( rows * uReliefFilter.y );
		vec2 gx = major * texel;
		vec2 gy = minor * texel;
		vec3 east = vec3( texel.x, 0.0, 0.0 );
		vec3 south = vec3( 0.0, texel.y, 0.0 );
		// Rise over two pixels of the window, then over the whole chart.
		vec2 rise = vec2(
			reliefHeight( st + east, gx, gy ) - reliefHeight( st - east, gx, gy ),
			reliefHeight( st + south, gx, gy ) - reliefHeight( st - south, gx, gy )
		) * 0.5 * grid.xy * uReliefFilter.y;
		bool onMap = window.x < 0.5;
		vec3 uphill = rise.x * ( onMap ? mapX : capX ) + rise.y * ( onMap ? mapY : capY );
		slope += ( 1.0 - covered ) * alpha * uphill;
		covered += ( 1.0 - covered ) * alpha;
		if ( covered > 0.995 ) break;
	}
	return slope * uReliefScale;
}
`;

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
		uniforms: {
			uReliefMap: chain.uniforms.map,
			uReliefMask: chain.uniforms.mask,
			uReliefGrid: chain.uniforms.grid,
			uReliefWindow: chain.uniforms.window,
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
