/**
 * Whether a body's ground hides a point from the camera, both given from the
 * body's centre in the same units. The line between them is tested against a
 * sphere at the lower of the two, no higher than `topRadius`, the highest the
 * ground reaches. Exact for a point on a sphere; near the ground the lower end
 * stands in for the relief between, so a camera in a basin still sees a lander
 * on the rim and a lander past the curve stays hidden. An orbiter is tested
 * against the ground itself.
 */
export function behindGround(
	px: number,
	py: number,
	pz: number,
	cx: number,
	cy: number,
	cz: number,
	topRadius = Infinity
): boolean {
	const p2 = px * px + py * py + pz * pz;
	const c2 = cx * cx + cy * cy + cz * cz;
	const ground2 = Math.min(p2, c2, topRadius * topRadius);
	// Along the line from C to P, the point nearest the centre is C + t·(P − C).
	const dx = px - cx;
	const dy = py - cy;
	const dz = pz - cz;
	const len2 = dx * dx + dy * dy + dz * dz;
	if (len2 === 0) return false;
	const t = -(cx * dx + cy * dy + cz * dz) / len2;
	if (t <= 0 || t >= 1) return false;
	const nx = cx + t * dx;
	const ny = cy + t * dy;
	const nz = cz + t * dz;
	return nx * nx + ny * ny + nz * nz < ground2;
}
