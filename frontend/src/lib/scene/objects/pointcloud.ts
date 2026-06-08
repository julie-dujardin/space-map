import {
	BufferAttribute,
	BufferGeometry,
	CanvasTexture,
	Color,
	Float32BufferAttribute,
	Points,
	PointsMaterial
} from 'three';
import type { PositionedBody } from '$lib/types/objects';

const F32_MAX = 3.4028235e38;

// Render after the planet's transparent overlays (clouds=1, atmosphere=2). All
// three are transparent + depthWrite=false; without an explicit order, points
// (renderOrder 0) get painted over by the cloud sphere's dark-side fragments —
// satellites geometrically in front of Earth visibly dim under the cloud layer.
const POINT_CLOUD_RENDER_ORDER = 3;

// Point-cloud dots read directly as the body's halo colour under ACES; scale
// down so they render as a darker shade rather than matching the halo.
function overlayColor(color: string): Color {
	return new Color(color).multiplyScalar(0.5);
}

export function makeCircleTexture(): CanvasTexture {
	const size = 32;
	const canvas = document.createElement('canvas');
	canvas.width = size;
	canvas.height = size;
	const ctx = canvas.getContext('2d')!;
	ctx.beginPath();
	ctx.arc(size / 2, size / 2, size / 2 - 2, 0, Math.PI * 2);
	ctx.fillStyle = '#aaaaaa';
	ctx.globalAlpha = 0.3;
	ctx.fill();
	return new CanvasTexture(canvas);
}

/**
 * Screen-space point size for the asteroid clouds. Smaller on phones so the
 * 1.3M-asteroid main belt doesn't visually swamp the planets at typical
 * mobile viewport scales. 768px matches the breakpoint used elsewhere
 * (DetailDrawer, SettingsButton).
 */
export function asteroidPointSize(): number {
	if (typeof window === 'undefined') return 3;
	return window.matchMedia('(max-width: 768px)').matches ? 2 : 3;
}

export function makePointCloud(
	bodies: PositionedBody[],
	texture: CanvasTexture,
	color: string,
	basisPos: [number, number, number] = [0, 0, 0],
	size: number = 4,
	colorForBody: ((body: PositionedBody) => string) | null = null
): Points {
	const valid = bodies.filter((b) => {
		const [x, y, z] = b.position;
		if (
			isFinite(x) &&
			Math.abs(x) <= F32_MAX &&
			isFinite(y) &&
			Math.abs(y) <= F32_MAX &&
			isFinite(z) &&
			Math.abs(z) <= F32_MAX
		)
			return true;
		console.warn(
			`Skipping body with non-finite position: id=${b.data.id} name=${b.data.name}`,
			b.position
		);
		return false;
	});
	const positions = new Float32Array(valid.length * 3);
	const colors = colorForBody ? new Float32Array(valid.length * 3) : null;
	const tmp = colors ? new Color() : null;
	for (let i = 0; i < valid.length; i++) {
		const b = valid[i];
		positions[i * 3] = b.position[0] - basisPos[0];
		positions[i * 3 + 1] = b.position[1] - basisPos[1];
		positions[i * 3 + 2] = b.position[2] - basisPos[2];
		if (colors && tmp && colorForBody) {
			tmp.set(colorForBody(b));
			colors[i * 3] = tmp.r;
			colors[i * 3 + 1] = tmp.g;
			colors[i * 3 + 2] = tmp.b;
		}
	}
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
	if (colors) geometry.setAttribute('color', new Float32BufferAttribute(colors, 3));
	const material = new PointsMaterial({
		map: texture,
		// vertexColors path: material color is the 0.5 dim multiplier (vColor * 0.5).
		color: colors ? new Color(0.5, 0.5, 0.5) : overlayColor(color),
		vertexColors: !!colors,
		transparent: true,
		size,
		sizeAttenuation: false,
		depthTest: true,
		depthWrite: false
	});
	const points = new Points(geometry, material);
	points.frustumCulled = false; // visibility managed by context-manager thresholds
	points.renderOrder = POINT_CLOUD_RENDER_ORDER;
	return points;
}

/**
 * Build a Points object whose position attribute is backed by a caller-owned
 * Float32Array. The same array is kept for the Points' lifetime — callers
 * mutate it in place and set `position.needsUpdate = true` so Three.js reuses
 * the same WebGL VBO (`bufferSubData`) instead of allocating a fresh one.
 *
 * `drawCount` controls the initial draw range; the caller updates it via
 * geometry.setDrawRange() when a worker returns a different valid count.
 */
export function makePointCloudFromBuffer(
	positions: Float32Array,
	drawCount: number,
	texture: CanvasTexture,
	color: string,
	size: number = 4,
	colors: Float32Array | null = null
): Points {
	const geometry = new BufferGeometry();
	geometry.setAttribute('position', new BufferAttribute(positions, 3));
	if (colors) geometry.setAttribute('color', new BufferAttribute(colors, 3));
	geometry.setDrawRange(0, drawCount);
	const material = new PointsMaterial({
		map: texture,
		color: colors ? new Color(0.5, 0.5, 0.5) : overlayColor(color),
		vertexColors: !!colors,
		transparent: true,
		size,
		sizeAttenuation: false,
		depthTest: true,
		depthWrite: false
	});
	const points = new Points(geometry, material);
	points.frustumCulled = false;
	points.renderOrder = POINT_CLOUD_RENDER_ORDER;
	return points;
}
