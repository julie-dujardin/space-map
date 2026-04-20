import type { Group, Mesh, Line, Object3D, Points, Sprite } from 'three';
import type { Lensflare } from 'three/addons/objects/Lensflare.js';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import type { NutPrec, Orientation } from '$lib/math/orientation';
import { ObjectType, type PositionedBody } from '$lib/types/objects';

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
	/** Top-level scene objects that track this body's position (corona, lensflare). */
	extraObjects: Object3D[];
	/** Star corona glow sprite (for manual occlusion). */
	corona: Sprite | null;
	/** Star lensflare (for manual occlusion). */
	lensflare: Lensflare | null;
	/** Fixed-size star dot shown when the mesh is sub-pixel. */
	starPoint: Points | null;
	orbitLine: Line | null;
	radiusScene: number;
	/** Cached distance from camera, computed once per frame. */
	cachedDist: number;
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
	/** Guard: a tier upgrade is currently in flight. */
	textureLoading?: boolean;
	/** Cached screen-pixel width of the label name text (measured once). */
	labelTextWidth?: number;
	/** Cached IAU orientation (pole + spin) so the mesh can be re-oriented per frame. */
	orientation?: Orientation;
	/** Cached IAU nutation/precession sums (per-body coefficients + system-shared angles). */
	nutPrec?: NutPrec;
}

export interface Callbacks {
	onFocusChange(body: PositionedBody | undefined): void;
	onCameraPosition?(latitude: number, longitude: number, zoom: number): void;
}
