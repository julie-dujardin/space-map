import type { PositionedBody, Unplaced } from '$lib/types/objects';

type Vec3 = [number, number, number];
type Writable = { -readonly [K in keyof PositionedBody]: PositionedBody[K] };

/** The scene origin. Only the Solar System barycentre is there. Frozen: a
 *  write to it throws. */
export const SSB_POSITION = Object.freeze([0, 0, 0]) as unknown as Vec3;

/** Put `body` at a place. A non-finite place is no place. */
export function setPlaced(body: PositionedBody, x: number, y: number, z: number): Vec3 | null {
	if (!Number.isFinite(x + y + z)) return setUnplaced(body, 'failed');
	const b = body as Writable;
	const p = (b.position ??= [0, 0, 0]);
	p[0] = x;
	p[1] = y;
	p[2] = z;
	b.unplaced = undefined;
	return p;
}

/** Take the place of `body` away, with the reason. */
export function setUnplaced(body: PositionedBody, why: Unplaced): null {
	const b = body as Writable;
	b.position = null;
	b.orbitCenter = b.orbitCenterId === undefined ? undefined : null;
	b.unplaced = why;
	return null;
}

/** Record where the orbit centre of `body` is. `null`: that body has no place. */
export function setOrbitCenter(body: PositionedBody, center: Readonly<Vec3> | null): void {
	const b = body as Writable;
	if (!center) {
		b.orbitCenter = null;
		return;
	}
	const c = (b.orbitCenter ??= [0, 0, 0]);
	c[0] = center[0];
	c[1] = center[1];
	c[2] = center[2];
}

/** Record where the bright end of the trail is. */
export function setTrailAnchor(body: PositionedBody, at: Readonly<Vec3>): void {
	const a = (body.trailAnchor ??= [0, 0, 0]);
	a[0] = at[0];
	a[1] = at[1];
	a[2] = at[2];
}
