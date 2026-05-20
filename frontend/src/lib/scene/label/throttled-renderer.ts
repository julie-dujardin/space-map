/**
 * Drop-in replacement for three/addons/renderers/CSS2DRenderer with per-element
 * write caching. Same traversal/projection semantics; skips style.transform,
 * style.display, and style.zIndex writes when the target value matches what we
 * last wrote.
 *
 * Why: CSS2DRenderer rewrites style.transform for every visible label every
 * frame, even when the label hasn't moved. On Firefox/Android style recalc is
 * the slow path and the per-frame churn is a major flicker contributor during
 * steady state (paused time, still camera). When nothing has changed the
 * throttle skips the DOM write entirely.
 *
 * Sub-pixel-equality is intentionally exact (not rounded): when nothing moves,
 * matrix multiplies are bit-stable across frames, so exact compare catches the
 * static case. When the camera or body is moving the values differ on every
 * frame and the write happens — same as upstream, no animation loss.
 */
import { Matrix4, Vector3, type Camera, type Object3D } from 'three';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

type CacheEntry = {
	tx: number;
	ty: number;
	cx: number;
	cy: number;
	display: string;
	zIndex: number;
	dist2: number;
};

interface CSS2DLike extends Object3D {
	isCSS2DObject: true;
	element: HTMLElement;
	center: { x: number; y: number };
}

function isCSS2D(o: Object3D): o is CSS2DLike {
	return (o as unknown as { isCSS2DObject?: boolean }).isCSS2DObject === true;
}

const SENTINEL = Number.NaN;

export class ThrottledCSS2DRenderer {
	readonly domElement: HTMLElement;
	sortObjects = true;

	private _w = 0;
	private _h = 0;
	private _wHalf = 0;
	private _hHalf = 0;

	private readonly _viewMatrix = new Matrix4();
	private readonly _viewProjectionMatrix = new Matrix4();
	private readonly _vector = new Vector3();
	private readonly _a = new Vector3();
	private readonly _b = new Vector3();

	private readonly _cache = new WeakMap<HTMLElement, CacheEntry>();
	private readonly _visibleBuf: CSS2DLike[] = [];
	private _visibleCount = 0;

	// telemetry — populated each render; readable from devtools for tuning
	skippedTransformWrites = 0;
	skippedDisplayWrites = 0;
	skippedZIndexWrites = 0;
	totalTransformWrites = 0;
	totalDisplayWrites = 0;
	totalZIndexWrites = 0;

	constructor(parameters: { element?: HTMLElement } = {}) {
		this.domElement = parameters.element ?? document.createElement('div');
		this.domElement.style.overflow = 'hidden';
	}

	getSize(): { width: number; height: number } {
		return { width: this._w, height: this._h };
	}

	setSize(width: number, height: number): void {
		this._w = width;
		this._h = height;
		this._wHalf = width / 2;
		this._hHalf = height / 2;
		this.domElement.style.width = width + 'px';
		this.domElement.style.height = height + 'px';
	}

	render(scene: Object3D, camera: Camera): void {
		if ((scene as { matrixWorldAutoUpdate?: boolean }).matrixWorldAutoUpdate === true) {
			scene.updateMatrixWorld();
		}
		if (
			camera.parent === null &&
			(camera as { matrixWorldAutoUpdate?: boolean }).matrixWorldAutoUpdate === true
		) {
			camera.updateMatrixWorld();
		}

		this._viewMatrix.copy(camera.matrixWorldInverse);
		this._viewProjectionMatrix.multiplyMatrices(camera.projectionMatrix, this._viewMatrix);

		this.skippedTransformWrites = 0;
		this.skippedDisplayWrites = 0;
		this.skippedZIndexWrites = 0;
		this.totalTransformWrites = 0;
		this.totalDisplayWrites = 0;
		this.totalZIndexWrites = 0;

		this._visibleCount = 0;
		this.renderObject(scene, camera);

		if (this.sortObjects) this.zOrder();

		// Trim references in the reusable buffer so we don't pin removed labels.
		for (let i = this._visibleCount; i < this._visibleBuf.length; i++) {
			this._visibleBuf[i] = undefined as unknown as CSS2DLike;
		}
		this._visibleBuf.length = this._visibleCount;
	}

	private renderObject(object: Object3D, camera: Camera): void {
		if (object.visible === false) {
			this.hideObject(object);
			return;
		}

		if (isCSS2D(object)) {
			const element = object.element;

			this._vector.setFromMatrixPosition(object.matrixWorld);
			this._vector.applyMatrix4(this._viewProjectionMatrix);
			const z = this._vector.z;
			const inFrustum = z >= -1 && z <= 1;
			const layerOk = object.layers.test(camera.layers);
			const visible = inFrustum && layerOk;

			let cache = this._cache.get(element);
			if (!cache) {
				cache = {
					tx: SENTINEL,
					ty: SENTINEL,
					cx: SENTINEL,
					cy: SENTINEL,
					display: '__init__',
					zIndex: SENTINEL,
					dist2: 0
				};
				this._cache.set(element, cache);
			}

			const targetDisplay = visible ? '' : 'none';
			if (cache.display !== targetDisplay) {
				element.style.display = targetDisplay;
				cache.display = targetDisplay;
				this.totalDisplayWrites++;
			} else {
				this.skippedDisplayWrites++;
			}

			if (visible) {
				// Upstream calls object.onBeforeRender / onAfterRender here. Our
				// CSS2DObjects never override these (they're Object3D no-ops in
				// factory.ts), so we skip the calls to avoid the wrong-signature
				// cast and a per-label function dispatch.
				const tx = this._vector.x * this._wHalf + this._wHalf;
				const ty = -this._vector.y * this._hHalf + this._hHalf;
				const cx = object.center.x;
				const cy = object.center.y;

				if (cache.tx !== tx || cache.ty !== ty || cache.cx !== cx || cache.cy !== cy) {
					element.style.transform =
						'translate(' + -100 * cx + '%,' + -100 * cy + '%) translate(' + tx + 'px,' + ty + 'px)';
					cache.tx = tx;
					cache.ty = ty;
					cache.cx = cx;
					cache.cy = cy;
					this.totalTransformWrites++;
				} else {
					this.skippedTransformWrites++;
				}

				if (element.parentNode !== this.domElement) {
					this.domElement.appendChild(element);
				}

				cache.dist2 = this.distanceToCameraSquared(camera, object);
				this._visibleBuf[this._visibleCount++] = object;
			}
		}

		const children = object.children;
		for (let i = 0; i < children.length; i++) {
			this.renderObject(children[i], camera);
		}
	}

	private hideObject(object: Object3D): void {
		if (isCSS2D(object)) {
			const element = object.element;
			let cache = this._cache.get(element);
			if (!cache) {
				cache = {
					tx: SENTINEL,
					ty: SENTINEL,
					cx: SENTINEL,
					cy: SENTINEL,
					display: '__init__',
					zIndex: SENTINEL,
					dist2: 0
				};
				this._cache.set(element, cache);
			}
			if (cache.display !== 'none') {
				element.style.display = 'none';
				cache.display = 'none';
				this.totalDisplayWrites++;
			} else {
				this.skippedDisplayWrites++;
			}
		}
		const children = object.children;
		for (let i = 0; i < children.length; i++) {
			this.hideObject(children[i]);
		}
	}

	private distanceToCameraSquared(camera: Object3D, object: Object3D): number {
		this._a.setFromMatrixPosition(camera.matrixWorld);
		this._b.setFromMatrixPosition(object.matrixWorld);
		return this._a.distanceToSquared(this._b);
	}

	private zOrder(): void {
		const visible = this._visibleBuf;
		const n = this._visibleCount;
		if (n === 0) return;

		visible.sort((a, b) => {
			if (a.renderOrder !== b.renderOrder) return b.renderOrder - a.renderOrder;
			const da = this._cache.get(a.element)!.dist2;
			const db = this._cache.get(b.element)!.dist2;
			return da - db;
		});

		const zMax = n;
		for (let i = 0; i < n; i++) {
			const obj = visible[i];
			const target = zMax - i;
			const cache = this._cache.get(obj.element)!;
			if (cache.zIndex !== target) {
				obj.element.style.zIndex = String(target);
				cache.zIndex = target;
				this.totalZIndexWrites++;
			} else {
				this.skippedZIndexWrites++;
			}
		}
	}
}

// Re-export the CSS2DObject type so callers can swap renderers without changing
// imports. CSS2DObject is still constructed via the upstream addon module.
export type { CSS2DObject };
