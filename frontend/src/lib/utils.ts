import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { BODY_COLORS, DEFAULT_BODY_COLOR } from './constants';
import { ObjectType } from './types/objects';

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
 */
export function resolveBodyColor(id: string, objectType: number): string {
	if (BODY_COLORS[id]) return BODY_COLORS[id];
	if (objectType === ObjectType.BARYCENTER) {
		if (id === 'naif-0') return BODY_COLORS['naif-10']; // Solar System Barycenter inherits Sun's color
		if (id === 'naif-9') return BODY_COLORS['spkid-20134340']; // Pluto's barycenter inherits Pluto's color
		const num = id.replace('naif-', '');
		const planetId = `naif-${num}99`;
		if (BODY_COLORS[planetId]) return BODY_COLORS[planetId];
	}
	return DEFAULT_BODY_COLOR;
}
