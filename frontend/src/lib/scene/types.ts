import type { Group, Line, Mesh, Object3D, Points, Sprite, Texture } from 'three';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import type { RingNode } from './objects/surface/rings';
import type { CloudNode } from './objects/surface/clouds';
import type { AtmosphereNode } from './objects/surface/atmosphere';
import type { EclipseSelfUniforms } from './objects/surface/eclipse-shadow';

// For focused objects:
// Body/halo size ratio at which the label should be hidden
export const HIDE_LABEL_BODY_HALO_FACTOR = 20;
export const HALO_RADIUS_PX = 16; // halo indicator is 32px diameter

export function typePriority(type: ObjectType): number {
	switch (type) {
		case ObjectType.STAR:
			return 0;
		case ObjectType.PLANET:
			return 1;
		case ObjectType.DWARF_PLANET:
			return 2;
		case ObjectType.MOON:
			return 3;
		default:
			return 4; // asteroid subtypes, comet, etc.
	}
}

export interface BodyObjects {
	body: PositionedBody;
	group: Group;
	mesh: Mesh | null;
	label: CSS2DObject | null;
	labelHalo: HTMLElement | null;
	/** Viewport-pinned loading spinner. Created by `setHaloLoading` only
	 *  while a GLB is in flight; visibility per-frame follows the close-zoom
	 *  rule (shown when the halo would be hidden). Lives outside the scene
	 *  graph so it doesn't drift with the focused body's per-frame motion. */
	loadingEl: HTMLElement | null;
	/** Top-level scene objects that track this body's position (corona, starPoint). */
	extraObjects: Object3D[];
	/** Star corona glow sprite (for manual occlusion). */
	corona: Sprite | null;
	/** Fixed-size star dot shown when the mesh is sub-pixel. */
	starPoint: Points | null;
	/** Thin trails are a `Line`; bodies with `lineWidth > 1` use a `Mesh` of expanded quads instead. */
	trail: Line | Mesh | null;
	radiusScene: number;
	/**
	 * True once the body's SPICE triaxial radii (`global.radii` or system meta
	 * `radii`) have been applied to the mesh as a non-uniform scale. Gates
	 * double-application: re-scaling against the now-bumped `radiusScene`
	 * would produce a stretched ellipsoid. Reset on mesh teardown.
	 */
	radiiApplied?: boolean;
	/** Cached distance from camera, computed once per frame. */
	cachedDist: number;
	/**
	 * Width/height segment count of the mesh's current `SphereGeometry`. The
	 * per-frame sphere LOD pass swaps the geometry when the desired count
	 * changes; `undefined` for virtual bodies (no mesh).
	 */
	currentSegments?: number;
	/**
	 * True when the current simulation `jd` is outside this body's chunk
	 * validity window — set by `computePosition` each frame and read by
	 * `updateBodyVisibility` to force the group hidden. Keeps the mesh at its
	 * last valid position instead of letting SGP4 diverge / freezing a stuck
	 * satellite onscreen.
	 */
	outOfRange?: boolean;
	/** Texture resolution tiers available for this body (e.g. ['low', 'medium', 'high']). */
	availableTiers?: string[];
	/** Currently loaded texture tier name. */
	textureTier?: string;
	/**
	 * Frame count for `cylindrical_monthly` textures (12 today). Undefined for
	 * single-frame bodies. The renderer reloads the texture when the simulation
	 * date crosses into the next frame's slot.
	 */
	availableFrames?: number;
	/** Currently loaded 1-based frame index for monthly textures (1..availableFrames). */
	textureFrame?: number;
	/** Guard: a tier or frame swap is currently in flight. */
	textureLoading?: boolean;
	/** Cached screen-pixel width of the label name text (measured once). */
	labelTextWidth?: number;
	/**
	 * Minor-promoted halo: rendered as a small ring (no name, no trail) by
	 * default; expands and reveals its label on hover; trail draws on focus.
	 * Membership is fixed at construction from {@link MINOR_PROMOTED_IDS}.
	 */
	isMinor: boolean;
	/**
	 * Planetary-ring annulus mesh + shader, populated by `loadSystemData` when
	 * the body's system metadata carries a `rings` block. The renderer keeps
	 * its position synced with the body and its orientation aligned with the
	 * body's pole each frame; `material.uniforms.uSunDir` is updated alongside.
	 */
	rings: RingNode | null;
	/**
	 * Cloud-overlay sphere, populated by `loadSystemData` when the body's
	 * system metadata carries a `clouds` block. Parented to `mesh`, so it
	 * inherits the body's flattening + IAU rotation automatically. Tier swaps
	 * are driven by the same LOD pass that upgrades the surface texture.
	 */
	clouds: CloudNode | null;
	/**
	 * Atmospheric-scattering shell, built at construction for bodies listed in
	 * `ATMOSPHERE_PARAMS` (Earth today). A sibling scene object kept at the
	 * body's centre via `extraObjects`; the renderer pushes the body→Sun
	 * direction onto its `material.uniforms.uSunDir` each frame.
	 */
	atmosphere: AtmosphereNode | null;
	/**
	 * Loaded specular/roughness map, populated by `loadSystemData` when the
	 * body's system metadata carries a `specular` block. Bound to the body's
	 * material as a `roughnessMap` with a shader patch that inverts the
	 * sampled value — held here for disposal on system unload. Stays at the
	 * low tier today; the binary mask doesn't benefit from LOD upgrades.
	 */
	specularMap: Texture | null;
	/**
	 * Per-body eclipse-shadow uniforms — present on every non-star body,
	 * `null` on stars and barycenters. The renderer mutates
	 * `uEclipseSelfPos` each frame so the body's fragment shader can skip
	 * self-occlusion when scanning the scene-wide occluder array.
	 */
	eclipseShadow: EclipseSelfUniforms | null;
	/**
	 * Loaded GLTF root for spacecraft 3D models. Populated by `loadBodyModel`
	 * on focus when the body's global JSON carries `model_name`; `null` when
	 * the body has no model or hasn't been focused yet. Tracked alongside the
	 * body's position via `extraObjects` so {@link repositionBodies} keeps it
	 * locked to the body each frame. Disposed in `unloadBodyModel`.
	 */
	model: Object3D | null;
	/** Slug of the currently loaded model bundle (matches `global.model_name`). */
	modelName?: string;
	/** Guard against re-entering `loadBodyModel` while a fetch is in flight. */
	modelLoading?: boolean;
	/** Bumped by `unloadBodyModel`; in-flight `loadBodyModel` invocations
	 *  re-check it after each await and abort if it changed. */
	modelLoadEpoch?: number;
}

export interface Callbacks {
	onFocusChange(body: PositionedBody | undefined): void;
	onCameraPosition?(latitude: number, longitude: number, zoom: number): void;
	/** Number of user-promoted bodies that can be cleared (excludes the focused
	 *  body — clearing it would leave the camera pointed at a torn-down mesh). */
	onUserPromotedChange?(count: number): void;
}
