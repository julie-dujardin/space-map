import { Vector3, type PerspectiveCamera } from 'three';
import { HALO_RADIUS_PX, type BodyObjects } from '../types';
import type { Vec3 } from '../animation/math';

/**
 * Debug overlay for the per-body silhouette "virtual halo" the visibility pass
 * uses for label placement + occlusion. Draws the disc for every on-screen mesh
 * (even hidden-label ones) so name-drift and bad occlusion become visible.
 *
 *  cyan — label shown · yellow — dimmed · red — hidden
 *  orange — occluder · lime — true silhouette · green — focused
 *  red link — label buried by that occluder
 */
export class HaloDebugOverlay {
	private canvas: HTMLCanvasElement | null = null;
	private gfx: CanvasRenderingContext2D | null = null;
	private readonly tmp = new Vector3();
	private readonly items: HaloItem[] = [];

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

		// Pass 1: project every mesh into screen-space halo data, mirroring
		// updateBodyVisibility. Not gated on group.visible (nor is the real occluder
		// set) so a culled-but-large mesh still shows as an occluder.
		const halfW = screenW * 0.5;
		const halfH = screenH * 0.5;
		let n = 0;
		for (const bo of bodyObjects.values()) {
			const { label, group, radiusScene: r } = bo;
			if (!label || r <= 0) continue;
			const [bx, by, bz] = bo.body.position;

			// Camera-frame center — drives the cone test and the exact silhouette.
			this.tmp.set(bx - fx, by - fy, bz - fz).applyMatrix4(camInverse);
			const camX = this.tmp.x;
			const camY = this.tmp.y;
			const camZ = this.tmp.z;
			if (camZ >= 0) continue; // center behind camera
			const d2 = camX * camX + camY * camY + camZ * camZ;
			if (d2 <= r * r) continue; // camera inside the sphere

			// Ellipse axes are real only when the limb stays in front of the camera
			// plane (Bz² > r²); closer than that it's an unbounded hyperbola.
			const denom = camZ * camZ - r * r;
			const degenerate = denom <= 0;
			const bMinor = degenerate ? 0 : (r * projScale) / Math.sqrt(denom);
			const aMajor = degenerate ? 0 : (r * projScale * Math.sqrt(d2 - r * r)) / denom;
			const isOcc = degenerate || bMinor >= HALO_RADIUS_PX;

			// Raw projected body center + silhouette-corrected anchor (name spot).
			this.tmp.set(bx - fx, by - fy, bz - fz).project(camera);
			const cx = (this.tmp.x * 0.5 + 0.5) * screenW;
			const cy = (-this.tmp.y * 0.5 + 0.5) * screenH;
			const lp = label.position;
			this.tmp.set(bx - fx + lp.x, by - fy + lp.y, bz - fz + lp.z).project(camera);
			const hx = (this.tmp.x * 0.5 + 0.5) * screenW;
			const hy = (-this.tmp.y * 0.5 + 0.5) * screenH;

			const it = this.ensureItem(n++);
			it.id = bo.body.data.id;
			it.camX = camX;
			it.camY = camY;
			it.camZ = camZ;
			it.cx = cx;
			it.cy = cy;
			it.hx = hx;
			it.hy = hy;
			it.r = bMinor;
			it.aMajor = aMajor;
			it.worldR = r;
			it.degenerate = degenerate;
			const rxx = hx - halfW;
			const ryy = hy - halfH;
			const rlen = Math.hypot(rxx, ryy) || 1;
			it.rdx = rxx / rlen;
			it.rdy = ryy / rlen;
			it.dist = bo.cachedDist;
			it.isOccluder = isOcc;
			it.meshHidden = !group.visible;
			it.labelVisible = label.visible;
			it.maximized = bo.labelMaximized !== false;
			it.focused = bo.body.data.id === focusedBodyId;
			it.occludedBy = -1;
		}

		// Pass 2: occlusion — find a closer occluder burying each label, for the link.
		for (let i = 0; i < n; i++) {
			const it = this.items[i];
			for (let j = 0; j < n; j++) {
				const occ = this.items[j];
				if (!occ.isOccluder || occ.id === it.id || occ.dist >= it.dist) continue;
				// Tangent-cone test, identical to isScreenOccluded.
				const u = it.hx - halfW;
				const v = halfH - it.hy;
				const root = u * occ.camX + v * occ.camY - projScale * occ.camZ;
				if (root <= 0) continue;
				const k = occ.dist * occ.dist - occ.worldR * occ.worldR;
				if (root * root > k * (u * u + v * v + projScale * projScale)) {
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

			// Occluders draw as the silhouette ellipse; small bodies as circles;
			// degenerate occluders rely on the lime outline below. Hidden-mesh dashes.
			let drewShape = false;
			g.beginPath();
			if (it.isOccluder && !it.degenerate) {
				g.ellipse(it.hx, it.hy, it.aMajor, it.r, Math.atan2(it.rdy, it.rdx), 0, Math.PI * 2);
				drewShape = true;
			} else if (!it.isOccluder) {
				g.arc(it.hx, it.hy, it.r, 0, Math.PI * 2);
				drewShape = true;
			}
			if (drewShape) {
				g.strokeStyle = color;
				g.lineWidth = it.isOccluder ? 2 : 1;
				if (it.meshHidden) g.setLineDash([5, 4]);
				g.stroke();
				g.setLineDash([]);
				if (it.isOccluder) {
					g.fillStyle = 'rgba(255,140,26,0.08)';
					g.fill();
				}
			}

			// True projected silhouette (lime) — should match the orange ellipse.
			if (it.isOccluder) {
				this.drawSilhouette(g, it, camera, screenW, screenH);
			}

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
				g.fillText(it.id, it.hx + Math.min(it.r, 40) + 3, it.hy);
			}
		}

		drawLegend(g, screenH);
	}

	/**
	 * Stroke a sphere's exact projected silhouette via its horizon circle: center
	 * H = B·(d²−r²)/d², radius ρ = r·√(d²−r²)/d, in the plane ⊥ B. Manual w-divide
	 * so points behind the camera drop cleanly (handles the degenerate case).
	 */
	private drawSilhouette(
		g: CanvasRenderingContext2D,
		it: HaloItem,
		camera: PerspectiveCamera,
		screenW: number,
		screenH: number
	): void {
		const { camX, camY, camZ, worldR: r } = it;
		const d2 = camX * camX + camY * camY + camZ * camZ;
		const d = Math.sqrt(d2);
		if (d <= r) return;
		const hk = (d2 - r * r) / d2;
		const rho = (r * Math.sqrt(d2 - r * r)) / d;
		const hx = camX * hk;
		const hy = camY * hk;
		const hz = camZ * hk;

		// Orthonormal basis e1,e2 ⊥ B.
		const bx = camX / d;
		const by = camY / d;
		const bz = camZ / d;
		let ax = 0;
		const ay = 0;
		let az = 1;
		if (Math.abs(bz) > 0.9) {
			ax = 1;
			az = 0;
		}
		let e1x = ay * bz - az * by;
		let e1y = az * bx - ax * bz;
		let e1z = ax * by - ay * bx;
		const e1n = Math.hypot(e1x, e1y, e1z) || 1;
		e1x /= e1n;
		e1y /= e1n;
		e1z /= e1n;
		const e2x = by * e1z - bz * e1y;
		const e2y = bz * e1x - bx * e1z;
		const e2z = bx * e1y - by * e1x;

		const m = camera.projectionMatrix.elements;
		const N = 72;
		g.beginPath();
		let started = false;
		for (let i = 0; i <= N; i++) {
			const ph = (i / N) * Math.PI * 2;
			const cs = Math.cos(ph);
			const sn = Math.sin(ph);
			const px = hx + rho * (cs * e1x + sn * e2x);
			const py = hy + rho * (cs * e1y + sn * e2y);
			const pz = hz + rho * (cs * e1z + sn * e2z);
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
		g.strokeStyle = '#9bff00';
		g.lineWidth = 1.5;
		g.stroke();
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
				cx: 0,
				cy: 0,
				hx: 0,
				hy: 0,
				r: 0,
				aMajor: 0,
				rdx: 1,
				rdy: 0,
				dist: 0,
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
	/** Camera-frame body center, for the exact-silhouette draw. */
	camX: number;
	camY: number;
	camZ: number;
	/** Scene-unit body radius. */
	worldR: number;
	cx: number;
	cy: number;
	hx: number;
	hy: number;
	/** Semi-minor (tangential) silhouette axis in px. */
	r: number;
	/** Semi-major (radial) silhouette axis in px. */
	aMajor: number;
	/** Unit radial direction the major axis runs along. */
	rdx: number;
	rdy: number;
	dist: number;
	isOccluder: boolean;
	/** Limb crosses the camera plane (Bz² ≤ r²): no bounded screen ellipse. */
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
	['#ff8c1a', 'occluder ellipse (code)'],
	['#9bff00', 'true silhouette (should match)'],
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
