/**
 * CSS2DRenderer drop-in that caches per-element style writes so static labels
 * skip DOM writes — avoids Firefox/Android style recalc churn on still frames.
 * Transform compare is exact (matrix multiplies are bit-stable when nothing moves).
 */
import { Matrix4, Vector3, type Camera, type Object3D } from 'three';
import type { CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
import { ndcZVisible } from '$lib/scene/setup/depth-mode';

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
			// A hidden subtree is walked once; its labels stay hidden until it shows.
			if (object.userData.css2dHidden !== true) {
				this.hideObject(object);
				object.userData.css2dHidden = true;
			}
			return;
		}
		if (object.userData.css2dHidden === true) object.userData.css2dHidden = false;

		if (isCSS2D(object)) {
			const element = object.element;

			this._vector.setFromMatrixPosition(object.matrixWorld);
			this._vector.applyMatrix4(this._viewProjectionMatrix);
			const z = this._vector.z;
			const inFrustum = ndcZVisible(z);
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
			}

			if (visible) {
				// Half-pixel steps: a label that drifts less than that between
				// frames keeps its transform, so a still camera writes no styles.
				const tx = Math.round((this._vector.x * this._wHalf + this._wHalf) * 2) / 2;
				const ty = Math.round((-this._vector.y * this._hHalf + this._hHalf) * 2) / 2;
				const cx = object.center.x;
				const cy = object.center.y;

				if (cache.tx !== tx || cache.ty !== ty || cache.cx !== cx || cache.cy !== cy) {
					element.style.transform =
						'translate(' + -100 * cx + '%,' + -100 * cy + '%) translate(' + tx + 'px,' + ty + 'px)';
					cache.tx = tx;
					cache.ty = ty;
					cache.cx = cx;
					cache.cy = cy;
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
			}
		}
	}
}

export type { CSS2DObject };
