import { Quaternion, Vector3, type PerspectiveCamera } from 'three';
import { HALO_RADIUS_PX, type BodyObjects } from '../types';
import { isScreenOccluded, type ScreenOccluder } from '../label/culling';
import {
	ellipsoidCameraAxes,
	setSphereOccluder,
	setEllipsoidOccluder
} from '../visibility/ellipsoid';
import type { Vec3 } from '../animation/math';

/**
 * Debug overlay for the per-body silhouette "virtual halo" the visibility pass
 * uses for label placement + occlusion. Draws the exact projected silhouette for
 * every on-screen mesh (even hidden-label ones), so name-drift and bad occlusion
 * become visible. Oblate bodies draw as their true (flattened) silhouette, the
 * same ellipsoid the occlusion test uses.
 *
 *  cyan — label shown · yellow — dimmed · red — hidden
 *  orange — occluder silhouette · green — focused · red link — buried label
 */
export class HaloDebugOverlay {
	private canvas: HTMLCanvasElement | null = null;
	private gfx: CanvasRenderingContext2D | null = null;
	private readonly tmp = new Vector3();
	private readonly tmpQ = new Quaternion();
	private readonly items: HaloItem[] = [];
	// Scratch single-occluder array so Pass 2 can reuse the production cone test.
	private readonly one: ScreenOccluder[] = [];

	constructor(private readonly anchor: HTMLCanvasElement) {}

	get active(): boolean {
		return this.canvas !== null;
	}

	setVisible(visible: boolean): void {
		if (visible) {
			if (this.canvas) return;
			const c = document.createElement('canvas');
			c.style.cssText =
				'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:5';
			// Sit directly over the WebGL canvas in the same relative wrapper.
			this.anchor.parentElement?.appendChild(c);
			this.canvas = c;
			this.gfx = c.getContext('2d');
		} else if (this.canvas) {
			this.canvas.remove();
			this.canvas = null;
			this.gfx = null;
		}
	}

	/** Redraw every on-screen mesh's virtual halo. `screenW/H` are CSS pixels. */
	draw(
		bodyObjects: Map<string, BodyObjects>,
		camera: PerspectiveCamera,
		focusTruePos: Vec3,
		focusedBodyId: string | undefined,
		screenW: number,
		screenH: number
	): void {
		const g = this.gfx;
		const c = this.canvas;
		if (!g || !c) return;

		const dpr = window.devicePixelRatio || 1;
		const bw = Math.round(screenW * dpr);
		const bh = Math.round(screenH * dpr);
		if (c.width !== bw || c.height !== bh) {
			c.width = bw;
			c.height = bh;
		}
		g.setTransform(dpr, 0, 0, dpr, 0, 0);
		g.clearRect(0, 0, screenW, screenH);
		g.font = '10px monospace';
		g.textBaseline = 'middle';

		const fovRad = (camera.fov * Math.PI) / 180;
		const projScale = screenH / (2 * Math.tan(fovRad / 2));
		const camInverse = camera.matrixWorldInverse;
		const [fx, fy, fz] = focusTruePos;
		const halfW = screenW * 0.5;
		const halfH = screenH * 0.5;

		// Pass 1: project every mesh into screen-space, mirroring updateBodyVisibility.
		// Not gated on group.visible (nor is the real occluder set) so a culled-but-
		// large mesh still shows as an occluder. Each item carries the same screen
		// occluder the production cone test consumes — sphere or oblate ellipsoid.
		let n = 0;
		for (const bo of bodyObjects.values()) {
			const { label, group, radiusScene: r } = bo;
			if (!label || r <= 0) continue;
			const [bx, by, bz] = bo.body.position;

			// Camera-frame center.
			this.tmp.set(bx - fx, by - fy, bz - fz).applyMatrix4(camInverse);
			const camX = this.tmp.x;
			const camY = this.tmp.y;
			const camZ = this.tmp.z;
			if (camZ >= 0) continue; // center behind camera
			const d2 = camX * camX + camY * camY + camZ * camZ;
			if (d2 <= r * r) continue; // camera inside the bounding sphere

			const it = this.ensureItem(n++);

			// Camera-space principal axes + semi-axes (sphere = camera axes, r).
			const isEllipsoid = !!(bo.semiAxesScene && bo.mesh);
			if (isEllipsoid) {
				const ax = ellipsoidCameraAxes(
					bo.mesh!.getWorldQuaternion(this.tmpQ),
					camInverse,
					bo.semiAxesScene!
				);
				it.e0.copy(ax.e[0]);
				it.e1.copy(ax.e[1]);
				it.e2.copy(ax.e[2]);
				it.sa[0] = ax.a[0];
				it.sa[1] = ax.a[1];
				it.sa[2] = ax.a[2];
				setEllipsoidOccluder(
					it.occ,
					camX,
					camY,
					camZ,
					ax,
					projScale,
					halfW,
					halfH,
					bo.body.data.id,
					bo.cachedDist
				);
			} else {
				it.e0.set(1, 0, 0);
				it.e1.set(0, 1, 0);
				it.e2.set(0, 0, 1);
				it.sa[0] = it.sa[1] = it.sa[2] = r;
				setSphereOccluder(
					it.occ,
					camX,
					camY,
					camZ,
					r,
					projScale,
					halfW,
					halfH,
					bo.body.data.id,
					bo.cachedDist
				);
			}

			// Bounding-sphere gate (matches the production occluder gate). Past the
			// limb (Bz² ≤ r²) the body engulfs the view → always an occluder.
			const bz2 = camZ * camZ;
			const denom = bz2 - r * r;
			const degenerate = denom <= 0;
			const bMinor = degenerate ? 0 : (r * projScale) / Math.sqrt(denom);
			const isOcc = degenerate || bMinor >= HALO_RADIUS_PX;

			// Raw projected body center + the actual label anchor (set by the
			// visibility pass in label.position — its silhouette-center offset).
			this.tmp.set(bx - fx, by - fy, bz - fz).project(camera);
			it.cx = (this.tmp.x * 0.5 + 0.5) * screenW;
			it.cy = (-this.tmp.y * 0.5 + 0.5) * screenH;
			const lp = label.position;
			this.tmp.set(bx - fx + lp.x, by - fy + lp.y, bz - fz + lp.z).project(camera);
			it.hx = (this.tmp.x * 0.5 + 0.5) * screenW;
			it.hy = (-this.tmp.y * 0.5 + 0.5) * screenH;

			it.id = bo.body.data.id;
			it.camX = camX;
			it.camY = camY;
			it.camZ = camZ;
			it.worldR = r;
			it.dist = bo.cachedDist;
			it.isEllipsoid = isEllipsoid;
			it.degenerate = degenerate;
			it.isOccluder = isOcc;
			it.meshHidden = !group.visible;
			it.labelVisible = label.visible;
			it.maximized = bo.labelMaximized !== false;
			it.focused = bo.body.data.id === focusedBodyId;
			it.occludedBy = -1;
		}

		// Pass 2: occlusion — find a closer occluder burying each label, for the
		// link. Reuses the production cone test verbatim via a 1-element array.
		for (let i = 0; i < n; i++) {
			const it = this.items[i];
			for (let j = 0; j < n; j++) {
				const occ = this.items[j];
				if (!occ.isOccluder || occ.id === it.id) continue;
				this.one[0] = occ.occ;
				this.one.length = 1;
				if (isScreenOccluded(it.hx, it.hy, it.dist, it.id, this.one)) {
					it.occludedBy = j;
					break;
				}
			}
		}

		// Pass 3: draw. A hidden mesh draws only if it's still an occluder.
		for (let i = 0; i < n; i++) {
			const it = this.items[i];
			if (it.meshHidden && !it.isOccluder) continue;
			const color = it.focused
				? '#7dff7d'
				: it.isOccluder
					? '#ff8c1a'
					: !it.labelVisible
						? '#ff3b3b'
						: it.maximized
							? '#1ae5ff'
							: '#ffe11a';

			// Exact projected silhouette (ellipsoid limb; circle for spheres).
			g.beginPath();
			if (it.meshHidden) g.setLineDash([5, 4]);
			const drew = this.strokeLimb(g, it, camera, screenW, screenH);
			if (drew) {
				g.strokeStyle = color;
				g.lineWidth = it.isOccluder ? 2 : 1;
				g.stroke();
				if (it.isOccluder) {
					g.fillStyle = 'rgba(255,140,26,0.08)';
					g.fill();
				}
			}
			g.setLineDash([]);

			// Anchor annotations — skipped when degenerate (anchor flies off-screen).
			if (!it.degenerate) {
				// Silhouette offset: raw center → anchor, cross at the raw center.
				const odx = it.hx - it.cx;
				const ody = it.hy - it.cy;
				if (odx * odx + ody * ody > 1) {
					g.beginPath();
					g.moveTo(it.cx, it.cy);
					g.lineTo(it.hx, it.hy);
					g.strokeStyle = 'rgba(255,225,26,0.5)';
					g.lineWidth = 1;
					g.stroke();
					drawCross(g, it.cx, it.cy, 4, '#ff3ad1');
				}

				// Occlusion link: red line toward the occluder's raw center.
				if (it.occludedBy >= 0) {
					const occ = this.items[it.occludedBy];
					g.beginPath();
					g.setLineDash([4, 3]);
					g.moveTo(it.hx, it.hy);
					g.lineTo(occ.cx, occ.cy);
					g.strokeStyle = 'rgba(255,59,59,0.9)';
					g.lineWidth = 1;
					g.stroke();
					g.setLineDash([]);
				}

				// Anchor dot + id.
				g.beginPath();
				g.arc(it.hx, it.hy, 1.5, 0, Math.PI * 2);
				g.fillStyle = color;
				g.fill();
				g.fillStyle = 'rgba(255,255,255,0.85)';
				g.fillText(it.id, it.hx + 8, it.hy);
			}
		}

		drawLegend(g, screenH);
	}

	/**
	 * Stroke a body's exact projected silhouette. The limb is the circle on the
	 * unit sphere (normalized space, where the ellipsoid is a sphere) facing the
	 * camera; mapping it back through the principal axes Σ aᵢ yᵢ eᵢ gives the true
	 * camera-space silhouette curve, which collapses to a circle for spheres.
	 * Manual w-divide so points behind the camera drop cleanly. Returns false if
	 * the camera is inside the body.
	 */
	private strokeLimb(
		g: CanvasRenderingContext2D,
		it: HaloItem,
		camera: PerspectiveCamera,
		screenW: number,
		screenH: number
	): boolean {
		const { camX, camY, camZ, e0, e1, e2, sa } = it;
		// Normalized center c' = (c·eᵢ/aᵢ).
		const cp0 = (camX * e0.x + camY * e0.y + camZ * e0.z) / sa[0];
		const cp1 = (camX * e1.x + camY * e1.y + camZ * e1.z) / sa[1];
		const cp2 = (camX * e2.x + camY * e2.y + camZ * e2.z) / sa[2];
		const L2 = cp0 * cp0 + cp1 * cp1 + cp2 * cp2;
		if (L2 <= 1) return false;
		const L = Math.sqrt(L2);
		const hk = (L2 - 1) / L2; // limb-circle center along c'
		const rho = Math.sqrt(L2 - 1) / L; // limb-circle radius
		const h0 = cp0 * hk;
		const h1 = cp1 * hk;
		const h2 = cp2 * hk;

		// Orthonormal basis ⊥ c' in normalized (principal-component) space.
		const ux = cp0 / L;
		const uy = cp1 / L;
		const uz = cp2 / L;
		let tx = 0;
		const ty = 0;
		let tz = 1;
		if (Math.abs(uz) > 0.9) {
			tx = 1;
			tz = 0;
		}
		let b1x = uy * tz - uz * ty;
		let b1y = uz * tx - ux * tz;
		let b1z = ux * ty - uy * tx;
		const b1n = Math.hypot(b1x, b1y, b1z) || 1;
		b1x /= b1n;
		b1y /= b1n;
		b1z /= b1n;
		const b2x = uy * b1z - uz * b1y;
		const b2y = uz * b1x - ux * b1z;
		const b2z = ux * b1y - uy * b1x;

		const m = camera.projectionMatrix.elements;
		const N = 72;
		let started = false;
		for (let i = 0; i <= N; i++) {
			const ph = (i / N) * Math.PI * 2;
			const cs = Math.cos(ph);
			const sn = Math.sin(ph);
			// Limb point in normalized principal-component coords.
			const y0 = h0 + rho * (cs * b1x + sn * b2x);
			const y1 = h1 + rho * (cs * b1y + sn * b2y);
			const y2 = h2 + rho * (cs * b1z + sn * b2z);
			// Back to camera space: X = Σ aᵢ yᵢ eᵢ.
			const px = sa[0] * y0 * e0.x + sa[1] * y1 * e1.x + sa[2] * y2 * e2.x;
			const py = sa[0] * y0 * e0.y + sa[1] * y1 * e1.y + sa[2] * y2 * e2.y;
			const pz = sa[0] * y0 * e0.z + sa[1] * y1 * e1.z + sa[2] * y2 * e2.z;
			const cw = m[3] * px + m[7] * py + m[11] * pz + m[15];
			if (cw <= 1e-6) {
				started = false; // behind camera — break the stroke
				continue;
			}
			const nx = (m[0] * px + m[4] * py + m[8] * pz + m[12]) / cw;
			const ny = (m[1] * px + m[5] * py + m[9] * pz + m[13]) / cw;
			const sx = (nx * 0.5 + 0.5) * screenW;
			const sy = (-ny * 0.5 + 0.5) * screenH;
			if (started) g.lineTo(sx, sy);
			else {
				g.moveTo(sx, sy);
				started = true;
			}
		}
		return true;
	}

	private ensureItem(idx: number): HaloItem {
		let it = this.items[idx];
		if (!it) {
			it = {
				id: '',
				camX: 0,
				camY: 0,
				camZ: 0,
				worldR: 0,
				e0: new Vector3(),
				e1: new Vector3(),
				e2: new Vector3(),
				sa: [0, 0, 0],
				occ: {
					cx0: 0,
					cy0: 0,
					f: 0,
					gxx: 0,
					gxy: 0,
					gxz: 0,
					gyx: 0,
					gyy: 0,
					gyz: 0,
					gzx: 0,
					gzy: 0,
					gzz: 0,
					cpx: 0,
					cpy: 0,
					cpz: 0,
					K: 0,
					id: '',
					dist: 0
				},
				cx: 0,
				cy: 0,
				hx: 0,
				hy: 0,
				dist: 0,
				isEllipsoid: false,
				isOccluder: false,
				degenerate: false,
				meshHidden: false,
				labelVisible: false,
				maximized: false,
				focused: false,
				occludedBy: -1
			};
			this.items[idx] = it;
		}
		return it;
	}

	dispose(): void {
		this.setVisible(false);
	}
}

type HaloItem = {
	id: string;
	/** Camera-frame body center. */
	camX: number;
	camY: number;
	camZ: number;
	/** Bounding-sphere radius (max semi-axis), scene units. */
	worldR: number;
	/** Camera-space principal axes (unit) + semi-axes (scene units). */
	e0: Vector3;
	e1: Vector3;
	e2: Vector3;
	sa: [number, number, number];
	/** Production screen occluder driving the exact cone test. */
	occ: ScreenOccluder;
	cx: number;
	cy: number;
	hx: number;
	hy: number;
	dist: number;
	isEllipsoid: boolean;
	isOccluder: boolean;
	/** Bounding-sphere limb crosses the camera plane (Bz² ≤ r²): no bounded ellipse. */
	degenerate: boolean;
	/** Mesh group is hidden but the disc still occludes — surfaced as dashed. */
	meshHidden: boolean;
	labelVisible: boolean;
	maximized: boolean;
	focused: boolean;
	/** Index into `items` of the occluder hiding this label, or -1. */
	occludedBy: number;
};

const LEGEND: [string, string][] = [
	['#1ae5ff', 'label shown'],
	['#ffe11a', 'dimmed'],
	['#ff3b3b', 'hidden'],
	['#ff8c1a', 'occluder silhouette'],
	['#7dff7d', 'focused']
];

function drawLegend(g: CanvasRenderingContext2D, screenH: number): void {
	const x = 8;
	const lineH = 13;
	// Bottom-left, growing upward so it clears the top-left debug panels.
	let y = screenH - 8 - (LEGEND.length - 1) * lineH;
	g.font = '10px monospace';
	g.textBaseline = 'middle';
	for (const [color, text] of LEGEND) {
		g.fillStyle = color;
		g.fillRect(x, y - 4, 8, 8);
		g.fillStyle = 'rgba(255,255,255,0.9)';
		g.fillText(text, x + 12, y);
		y += lineH;
	}
}

function drawCross(
	g: CanvasRenderingContext2D,
	x: number,
	y: number,
	s: number,
	color: string
): void {
	g.strokeStyle = color;
	g.lineWidth = 1;
	g.beginPath();
	g.moveTo(x - s, y);
	g.lineTo(x + s, y);
	g.moveTo(x, y - s);
	g.lineTo(x, y + s);
	g.stroke();
}
