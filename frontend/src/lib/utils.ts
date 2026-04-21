import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import {
	BODY_COLORS,
	DEFAULT_BODY_COLOR,
	TYPE_COLOR_ASTEROID,
	TYPE_COLOR_COMET,
	TYPE_COLOR_DEBRIS,
	TYPE_COLOR_MOON,
	TYPE_COLOR_PLANET,
	TYPE_COLOR_PROBE,
	TYPE_COLOR_SATELLITE,
	TYPE_COLOR_STAR
} from './constants';
import { isAsteroid, ObjectType, type BodyData } from './types/objects';

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type WithoutChild<T> = T extends { child?: any } ? Omit<T, 'child'> : T;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type WithoutChildren<T> = T extends { children?: any } ? Omit<T, 'children'> : T;
export type WithoutChildrenOrChild<T> = WithoutChildren<WithoutChild<T>>;
export type WithElementRef<T, U extends HTMLElement = HTMLElement> = T & { ref?: U | null };

/**
 * Resolve a display color for a body.
 * Barycenters inherit their planet's color (naif-N → naif-N99).
 * Lagrange points inherit their parent's color.
 * Falls back to a category color based on ObjectType; SPACECRAFT colors
 * split by parent (Earth → satellite, Sun → probe).
 */
export function resolveBodyColor(data: BodyData): string {
	if (BODY_COLORS[data.id]) return BODY_COLORS[data.id];
	const { objectType, parentId } = data;
	if (objectType === ObjectType.BARYCENTER) {
		if (data.id === 'naif-0') return BODY_COLORS['naif-10']; // Solar System Barycenter inherits Sun's color
		if (data.id === 'naif-9') return BODY_COLORS['spkid-20134340']; // Pluto's barycenter inherits Pluto's color
		const num = data.id.replace('naif-', '');
		const planetId = `naif-${num}99`;
		if (BODY_COLORS[planetId]) return BODY_COLORS[planetId];
	}
	if (objectType === ObjectType.STAR) return TYPE_COLOR_STAR;
	if (objectType === ObjectType.PLANET || objectType === ObjectType.DWARF_PLANET)
		return TYPE_COLOR_PLANET;
	if (objectType === ObjectType.MOON) return TYPE_COLOR_MOON;
	if (isAsteroid(objectType)) return TYPE_COLOR_ASTEROID;
	if (objectType === ObjectType.COMET) return TYPE_COLOR_COMET;
	if (objectType === ObjectType.DEBRIS) return TYPE_COLOR_DEBRIS;
	if (objectType === ObjectType.SPACECRAFT) {
		if (parentId === 'naif-399') return TYPE_COLOR_SATELLITE;
		if (parentId === 'naif-10') return TYPE_COLOR_PROBE;
	}
	return DEFAULT_BODY_COLOR;
}
