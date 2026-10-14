import {
	type MeshStandardMaterial,
	type PerspectiveCamera,
	RGBAFormat,
	SRGBColorSpace,
	Texture,
	UnsignedByteType,
	type Vector3,
	type WebGLRenderer
} from 'three';
import { tilesBase } from '$lib/fetch/data-base';
import { textureAllowed } from '$lib/host';
import { FIRST_TILE_LEVEL, WINDOW_TILES, neededLevel } from '$lib/scene/lod/tile-window';
import { maxTileWindows } from '$lib/scene/render-tier';
import { chainShaderHook } from '$lib/scene/shaders/program-cache-key';
import type { BodyObjects, TilesBlock } from '$lib/scene/types';
import {
	MAX_DRAWN,
	TILE_CHAIN_GLSL,
	type LoadedTile,
	type TileChain,
	type TileKind,
	chainLength,
	createChain,
	disposeChain,
	finestLevelAt,
	pointUnderCamera,
	restChain,
	updateChain
} from './tile-chain';

/**
 * Surface tiles drawn over a body's whole-globe map while the camera is close.
 *
 * The map stays bound as it is. On top of it sits a chain of tile windows
 * (see `tile-chain.ts`). A fragment blends the two windows on either side of
 * the level its own footprint asks for, and takes the map where no window
 * covers it or a tile is missing.
 */

export interface TileOverlay {
	material: MeshStandardMaterial;
	chain: TileChain;
}

const PARS = /* glsl */ `
varying vec3 vTileOff;
uniform sampler2DArray uTileMap;
uniform sampler2DArray uTileMask;
uniform vec4 uTileGrid[ ${MAX_DRAWN} ];
uniform vec4 uTileWindow[ ${MAX_DRAWN} ];
uniform vec2 uTileHome[ ${MAX_DRAWN} ];
uniform vec3 uTileAnchor;
uniform vec2 uTileFilter;
${TILE_CHAIN_GLSL}
vec3 tileColour( vec3 below ) {
	if ( uTileWindow[ 0 ].w < 0.5 ) return below;
	TileCharts charts = tileChartsFrom( uTileAnchor, vTileOff );

	float rows = ${WINDOW_TILES.toFixed(1)};
	vec3 colour = vec3( 0.0 );
	float covered = 0.0;
	for ( int i = 0; i < ${MAX_DRAWN}; i ++ ) {
		vec4 window = uTileWindow[ i ];
		if ( window.w < 0.5 ) break;
		vec2 spot;
		vec2 major;
		vec2 minor;
		float alpha = tileWindowWeight( charts, window, uTileGrid[ i ], uTileHome[ i ], uTileFilter, spot, major, minor );
		if ( alpha <= 0.0 ) continue;
		ivec3 slot = ivec3( int( mod( spot.x, rows ) ), int( mod( spot.y, rows ) ), int( window.y ) );
		alpha *= texelFetch( uTileMask, slot, 0 ).r;
		if ( alpha <= 0.0 ) continue;

		vec3 st = vec3( spot.x / rows, - spot.y / rows, window.y );
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

async function loadColourTile(url: string, signal: AbortSignal): Promise<LoadedTile> {
	const response = await fetch(url, { signal });
	if (!response.ok) throw new Error(`tile ${response.status}`);
	// Flipped at decode: a bitmap ignores the upload's flip flag.
	const bitmap = await createImageBitmap(await response.blob(), {
		imageOrientation: 'flipY',
		premultiplyAlpha: 'none',
		colorSpaceConversion: 'none'
	});
	const texture = new Texture(bitmap);
	texture.colorSpace = SRGBColorSpace;
	texture.flipY = false;
	texture.generateMipmaps = false;
	return {
		texture,
		release() {
			texture.dispose();
			bitmap.close();
		}
	};
}

const COLOUR_TILES: TileKind = {
	format: RGBAFormat,
	type: UnsignedByteType,
	colorSpace: SRGBColorSpace,
	load: loadColourTile
};

function createOverlay(material: MeshStandardMaterial): TileOverlay {
	const chain = createChain(COLOUR_TILES);
	chainShaderHook(material, 'surfaceTiles', (shader) => {
		Object.assign(shader.uniforms, {
			uTileMap: chain.uniforms.map,
			uTileMask: chain.uniforms.mask,
			uTileGrid: chain.uniforms.grid,
			uTileWindow: chain.uniforms.window,
			uTileHome: chain.uniforms.home,
			uTileAnchor: chain.uniforms.anchor,
			uTileFilter: chain.uniforms.filter
		});
		shader.vertexShader = shader.vertexShader
			.replace(
				'#include <common>',
				'#include <common>\nvarying vec3 vTileOff;\nuniform vec3 uTileAnchor;'
			)
			.replace(
				'#include <begin_vertex>',
				'#include <begin_vertex>\nvTileOff = position - uTileAnchor;'
			);
		shader.fragmentShader = shader.fragmentShader
			.replace('#include <map_pars_fragment>', `#include <map_pars_fragment>\n${PARS}`)
			.replace('#include <map_fragment>', MAP_FRAGMENT);
	});
	return { material, chain };
}

/** Free a body's tile windows. The shader hook stays, switched off. */
export function disposeTileOverlay(bo: BodyObjects): void {
	if (bo.tileOverlay) disposeChain(bo.tileOverlay.chain);
}

/** Whether surface tiles draw at all: they need a tile host, and memory this
 *  device does not always have. */
export function surfaceTilesEnabled(): boolean {
	return tilesBase() !== '' && maxTileWindows() > 0;
}

/** Whether this embed draws the pyramid `tiles` on this device. A body can
 *  still rule it out. */
export function tilesDrawable(tiles: TilesBlock | undefined): boolean {
	return (
		!!tiles &&
		tiles.max_level >= FIRST_TILE_LEVEL &&
		surfaceTilesEnabled() &&
		textureAllowed(tiles.distribution)
	);
}

/** Whether tiles carry this body's surface detail, so the largest whole-globe
 *  tier need not load. False once the tile host has failed it, and for a
 *  shape model, which takes the sphere's map and no windows. */
export function tilesServe(bo: BodyObjects): boolean {
	return tilesDrawable(bo.surfaceTiles) && !bo.model && !bo.tileOverlay?.chain.dead;
}

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
	let over: Vector3 | undefined;
	let level = -1;
	if (tiles && mesh && material?.map && drawable && tilesServe(bo)) {
		over = pointUnderCamera(mesh, camera);
		const finest = finestLevelAt(bo.tileOverlay?.chain, tiles, over);
		level = neededLevel(bo.radiusScene, bo.cachedDist, projScale, finest);
	}

	if (!tiles || !over || !material || level < FIRST_TILE_LEVEL) {
		if (bo.tileOverlay) restChain(bo.tileOverlay.chain, performance.now());
		return;
	}

	// A rebuilt mesh has a new material, without the hook.
	if (bo.tileOverlay && bo.tileOverlay.material !== material) {
		disposeTileOverlay(bo);
		bo.tileOverlay = undefined;
	}
	const overlay = (bo.tileOverlay ??= createOverlay(material));
	updateChain(
		overlay.chain,
		tiles,
		chainLength(tiles, maxTileWindows()),
		level,
		over,
		bo.radiusScene,
		tiles.frames ? bo.textureFrame : undefined,
		renderer,
		invalidate
	);
}
