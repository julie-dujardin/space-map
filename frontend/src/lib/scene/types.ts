import type { Group, Mesh, Line } from 'three';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
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
	orbitLine: Line | null;
	radiusScene: number;
}

export interface Callbacks {
	onFocusChange(body: PositionedBody | undefined): void;
	onCameraPosition?(latitude: number, longitude: number, zoom: number): void;
}
