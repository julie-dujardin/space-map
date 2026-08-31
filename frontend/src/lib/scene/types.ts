import type { Group, Line, Mesh, Object3D, Points, Sprite, Texture } from 'three';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { ObjectType, type PositionedBody } from '$lib/types/objects';
import type { LabelAnnotation } from './label/annotations';
import type { RingNode } from './objects/surface/rings';
import type { CloudNode } from './objects/surface/clouds';
import type { AtmosphereNode } from './objects/surface/atmosphere';
import type { EclipseSelfUniforms } from './objects/surface/eclipse-shadow';
import type { SunTransmittanceUniforms } from './objects/surface/sun-transmittance';
import type { SelfShadowUniforms } from './objects/surface/self-shadow';
import type { DisplacementMeta } from './objects/surface/displacement';
import type { TerrainWindowState } from './lod/terrain-window';

/** Mesh/halo screen-size ratio above which the body label is dropped: the mesh
 *  fills enough of the view to identify itself, and the silhouette-centre offset
 *  would otherwise strand the name out near the limb. */
export const HIDE_LABEL_BODY_HALO_FACTOR = 20;
/** Halo indicator radius — diameter is 32px. */
export const HALO_RADIUS_PX = 16;

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
	/** Stack of caption lines under the name, shown and hidden with it. Built on
	 *  demand by `setLabelAnnotation`; most bodies never get one. */
	labelStack: HTMLElement | null;
	/** The lines in that stack, by kind. */
	labelAnnotations?: Partial<Record<LabelAnnotation, HTMLElement>>;
	/** Viewport-pinned model-load spinner, shown when the halo would be hidden. */
	loadingEl: HTMLElement | null;
	/** Top-level scene objects that track this body's position. */
	extraObjects: Object3D[];
	corona: Sprite | null;
	starPoint: Points | null;
	/** Thin trails use `Line`; wider trails use a `Mesh` of expanded quads. */
	trail: Line | Mesh | null;
	radiusScene: number;
	/**
	 * True once SPICE triaxial radii have been applied as a non-uniform scale.
	 * Gates re-application against the now-bumped `radiusScene`. Reset on mesh teardown.
	 */
	radiiApplied?: boolean;
	/** Semi-axes (scene units) in mesh-local x/y/z order — set with the triaxial
	 *  scale. Present only on oblate bodies; drives ellipsoid label occlusion +
	 *  anchor placement. Undefined ⇒ treated as a sphere of `radiusScene`. */
	semiAxesScene?: [number, number, number];
	/** Cached distance from camera, computed once per frame. */
	cachedDist: number;
	/** Set per-frame by the visibility pre-pass: the label's right-limb anchor
	 *  projects outside the viewport, so the name would be off screen too. Drives
	 *  dropping it. */
	labelAnchorOffscreen?: boolean;
	/** Width/height segment count of the mesh's current SphereGeometry; undefined for virtual bodies. */
	currentSegments?: number;
	/**
	 * True when jd is outside this body's chunk validity window. `updateBodyVisibility`
	 * forces the group hidden so SGP4 doesn't diverge / a stale satellite stays onscreen.
	 */
	outOfRange?: boolean;
	availableTiers?: string[];
	textureTier?: string;
	/** Frame count for `cylindrical_monthly` textures; undefined for single-frame bodies. */
	availableFrames?: number;
	/** Currently loaded 1-based frame index (1..availableFrames). */
	textureFrame?: number;
	/** A tier or frame swap is currently in flight. */
	textureLoading?: boolean;
	/** Bumped on unload; an in-flight swap whose captured value is now stale
	 *  discards its result instead of re-attaching a texture that's no longer wanted. */
	textureLoadGen?: number;
	/** Cached screen-pixel width of the label name text. */
	labelTextWidth?: number;
	/** Minor-promoted halo: rendered as a small ring; expands on hover. From {@link MINOR_PROMOTED_IDS}. */
	isMinor: boolean;
	/** Ring bundles, inner → outer. Saturn owns three (D ring, measured main
	 *  rings, tenuous outer rings); the others one. Index 0 is not special —
	 *  the shadow caster is chosen by opacity when the bundles load. */
	rings: RingNode[];
	clouds: CloudNode | null;
	atmosphere: AtmosphereNode | null;
	/** Specular/roughness map. Stays at the low tier — binary mask doesn't benefit from LOD. */
	specularMap: Texture | null;
	/** Emissive night-lights map. Stays at the low tier — only sampled on the
	 *  unlit side, so fine detail isn't worth the bandwidth. */
	emissiveMap: Texture | null;
	/** Displacement/height map. Starts at the low tier; the texture-LOD pass
	 *  upgrades it by altitude so the terrain window has data to refine into. */
	displacementMap: Texture | null;
	/** Displacement metadata, kept for altitude-driven tier swaps. */
	displacementMeta?: DisplacementMeta;
	/** Loaded displacement tier; undefined while none is attached. */
	displacementTier?: string;
	/** A displacement tier swap is in flight. */
	displacementLoading?: boolean;
	/** Active close-zoom terrain window (non-uniform grid); null/undefined when
	 *  the mesh carries a uniform SphereGeometry. */
	terrainWindow?: TerrainWindowState | null;
	/** Terrain self-shadow + relief uniforms; set alongside the displacement map. */
	selfShadow: SelfShadowUniforms | null;
	/** Per-body eclipse-shadow uniforms; null on stars and barycenters. */
	eclipseShadow: EclipseSelfUniforms | null;
	/** Sun-transmittance patches on the body (and cloud) materials, kept so
	 *  {@link applyRadiiToMesh} can re-sync them to the SPICE equatorial radius
	 *  — their β/height normalisation is baked at attach time. */
	sunTint?: SunTransmittanceUniforms[];
	/** IAU nomenclature labels attached to the body mesh (sphere path) or to
	 *  {@link nomenclatureAnchor} (shape-model path); null when not loaded. */
	nomenclatureLabels: CSS2DObject[] | null;
	/** Identity-scale parent for shape-model feature labels — the hidden sphere
	 *  mesh can't host them (invisible + non-uniform triaxial scale). Receives
	 *  the same IAU orientation as the overlay model each frame. */
	nomenclatureAnchor?: Group | null;
	/** Parallel to {@link nomenclatureLabels}: effective feature diameter in metres,
	 *  with a fallback applied for IAU records that omit it. */
	nomenclatureDiamsM?: Float32Array;
	/** Parallel to {@link nomenclatureLabels}, shape-model path only: body-fixed
	 *  surface normals (xyz triplets) for the per-frame local-horizon test. */
	nomenclatureNormals?: Float32Array;
	/** Parallel to {@link nomenclatureLabels}: cached label text width in px; `-1`
	 *  until first successful `offsetWidth` measurement. */
	nomenclatureWidths?: Float32Array;
	/** Parallel to {@link nomenclatureLabels}: last computed screen-space center
	 *  written by the visibility pass; `NaN` when the label is hidden. Read by
	 *  the collision cull. */
	nomenclatureSX?: Float32Array;
	nomenclatureSY?: Float32Array;
	/** Index into {@link nomenclatureLabels} of the URL-selected feature, or
	 *  `-1` when none. The visibility + collision passes exempt this label
	 *  from per-feature size / hemisphere / overlap rejection so the focused
	 *  feature is always shown while the body-level zoom gate passes. */
	nomenclatureActiveIndex?: number;
	/** True iff the probe's landed record covers the current jd. Drives the
	 *  spacecraft halo glyph swap (flying → landed octagon). */
	isLanded?: boolean;
	/** Written by the throttled body cull. Lets the nomenclature cull skip
	 *  dimmed labels' rects, so it doesn't over-cull features against a
	 *  near-invisible body. Undefined before the first cull → treated as maximized. */
	labelMaximized?: boolean;
	/** Loaded GLTF root for spacecraft 3D models; null when not focused or no model bundle. */
	model: Object3D | null;
	/** Main-scene mount for a natural body's `model`: a wrapper under `group`
	 *  scaled to `modelUnitScene`, so unit-scale model conventions hold inside
	 *  it. Spacecraft models render in the overlay scene and have none. */
	modelRoot?: Group | null;
	/** Slug of the currently loaded model bundle. */
	modelName?: string;
	/** In-flight model load, shared by concurrent loadBodyModel calls so every
	 *  caller's settle-time work waits on the same load. */
	modelLoadPromise?: Promise<void>;
	/** Bumped by unload; in-flight loads re-check after each await and abort if it changed. */
	modelLoadEpoch?: number;
	/** Nothing physical to draw — drives the close-range note under the label.
	 *  `'radius'`: natural body, no measured size. `'model'`: spacecraft, no GLB. */
	noPhysical?: 'model' | 'radius';
	/** Focus has run `upgradeBodyMesh` on this body. Trails for halo-only types
	 *  are deferred until then, and `mesh` alone can't stand in for it: a body
	 *  with no measured size never gets a sphere, so it would wait forever. */
	focusUpgraded?: boolean;
}

export interface Callbacks {
	onFocusChange(body: PositionedBody | undefined): void;
	onCameraPosition?(latitude: number, longitude: number, zoom: number): void;
	/** Number of user-promoted bodies that can be cleared (excludes the focused
	 *  body — clearing it would leave the camera pointed at a torn-down mesh). */
	onUserPromotedChange?(count: number): void;
	/** Click on a nomenclature surface-feature label; carries lat/lon/diameterM
	 *  so the caller can fly the camera without another lookup. */
	onFeatureSelect?(
		bodyId: string,
		featureId: number,
		lat: number,
		lon: number,
		diameterM: number
	): void;
}
