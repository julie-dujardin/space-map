import {
	BufferGeometry,
	Color,
	LinearSRGBColorSpace,
	NoBlending,
	Points,
	RawShaderMaterial,
	Scene,
	WebGLRenderTarget,
	type Material,
	type PerspectiveCamera,
	type WebGLRenderer
} from 'three';

/**
 * GPU picking for the asteroid/spacecraft clouds (~1.3M dots): render a small
 * framebuffer box around the cursor with each dot's pick-id as its color, read
 * it back, return the nearest lit pixel's id. Exact and off the main thread,
 * where re-solving that many orbits per click would stutter.
 *
 * No meshes in the pass, so no planet occlusion — the caller rejects any
 * candidate hidden behind a mesh on its own ray.
 */
/** A `Points` of the pick pass and the material that writes its pick-ids. */
export interface PickDraw {
	points: Points;
	material: Material;
}

export interface PickCandidate {
	/** Decoded global pick-id; resolve via {@link PickRegistry}. */
	pickId: number;
	/** Distance in CSS px from the cursor to this dot. */
	pixelDist: number;
	/** The dot's NDC, for a caller-side occlusion raycast. */
	ndcX: number;
	ndcY: number;
}

/** Point-sprite size in the pick pass (CSS px). Small — the search radius, not
 *  the sprite, provides click tolerance — but wide enough that a ~2px visual dot
 *  always lights at least one pixel. */
const PICK_POINT_SIZE = 4;

/** Cap on distinct candidates returned; the caller only needs the nearest few to
 *  skip past any occluded by a mesh. */
const MAX_CANDIDATES = 16;

const VERT = `
uniform mat4 modelViewMatrix;
uniform mat4 projectionMatrix;
uniform float uPointSize;
attribute vec3 position;
attribute vec4 pickColor;
varying vec4 vPick;
void main() {
	vPick = pickColor;
	gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
	gl_PointSize = uPointSize;
}
`;

const FRAG = `
precision highp float;
varying vec4 vPick;
void main() {
	gl_FragColor = vPick;
}
`;

export class GpuPickPass {
	private readonly target: WebGLRenderTarget;
	private readonly material: RawShaderMaterial;
	private readonly scene = new Scene();
	private readonly pickCamera: PerspectiveCamera;
	private size = 0;
	private buffer = new Uint8Array(0);
	private readonly prevClear = new Color();
	/** Reused proxy Points wrapping live geometries, grown on demand. */
	private readonly proxies: Points[] = [];
	/** What a proxy holds between picks. */
	private readonly idleGeometry = new BufferGeometry();

	constructor(
		private readonly renderer: WebGLRenderer,
		camera: PerspectiveCamera
	) {
		this.target = new WebGLRenderTarget(1, 1, { depthBuffer: true });
		// Raw bytes must survive readback: no colour-space encoding on the target.
		this.target.texture.colorSpace = LinearSRGBColorSpace;
		this.target.texture.generateMipmaps = false;
		this.material = new RawShaderMaterial({
			vertexShader: VERT,
			fragmentShader: FRAG,
			uniforms: { uPointSize: { value: PICK_POINT_SIZE } },
			blending: NoBlending,
			depthTest: true,
			depthWrite: true
		});
		this.scene.matrixWorldAutoUpdate = false;
		this.pickCamera = camera.clone() as PerspectiveCamera;
	}

	private ensureSize(px: number): void {
		if (px === this.size) return;
		this.size = px;
		this.target.setSize(px, px);
		this.buffer = new Uint8Array(px * px * 4);
	}

	/** A proxy Points sharing `src`'s geometry, positioned at `src`'s world
	 *  transform. Reused across picks to avoid per-click allocation; the scene
	 *  is empty between picks. */
	private proxyAt(index: number, src: Points, material: Material): Points {
		let p = this.proxies[index];
		if (!p) {
			p = new Points(src.geometry, material);
			p.frustumCulled = false;
			p.matrixAutoUpdate = false;
			p.matrixWorldAutoUpdate = false;
			this.proxies[index] = p;
		} else {
			p.geometry = src.geometry;
			p.material = material;
		}
		p.matrixWorld.copy(src.matrixWorld);
		return p;
	}

	/**
	 * Render the given clouds around the cursor and return distinct pick-id
	 * candidates sorted nearest-first. Clouds without a `pickColor` attribute
	 * (not yet solved) are skipped.
	 */
	pick(
		clouds: Iterable<Points>,
		camera: PerspectiveCamera,
		clientX: number,
		clientY: number,
		rect: DOMRect,
		radiusCss: number
	): PickCandidate[] {
		const draws: PickDraw[] = [];
		for (const points of clouds) {
			if (!points.geometry.getAttribute('pickColor')) continue;
			draws.push({ points, material: this.material });
		}
		return this.pickDraws(draws, camera, clientX, clientY, rect, radiusCss);
	}

	/** {@link pick} for objects that bring their own pick material. One target
	 *  pixel is one CSS pixel, so a material sizes its points in CSS px. */
	pickDraws(
		draws: Iterable<PickDraw>,
		camera: PerspectiveCamera,
		clientX: number,
		clientY: number,
		rect: DOMRect,
		radiusCss: number
	): PickCandidate[] {
		const r = Math.max(1, Math.round(radiusCss));
		const boxPx = r * 2 + 1;
		this.ensureSize(boxPx);

		// Cursor in CSS px within the canvas; the box is centred on it.
		const cx = clientX - rect.left;
		const cy = clientY - rect.top;
		const offsetX = cx - r;
		const offsetY = cy - r;

		let n = 0;
		for (const { points, material } of draws) {
			if (!points.visible) continue;
			if (points.geometry.drawRange.count === 0) continue;
			this.scene.add(this.proxyAt(n++, points, material));
		}
		if (n === 0) return [];

		// Render only the cursor's box: setViewOffset maps that CSS sub-rect to the
		// full (boxPx²) target, so one target pixel = one CSS pixel.
		this.pickCamera.copy(camera);
		this.pickCamera.setViewOffset(rect.width, rect.height, offsetX, offsetY, boxPx, boxPx);
		this.pickCamera.updateProjectionMatrix();

		const prevTarget = this.renderer.getRenderTarget();
		const prevAutoClear = this.renderer.autoClear;
		this.renderer.getClearColor(this.prevClear);
		const prevClearAlpha = this.renderer.getClearAlpha();
		this.renderer.setRenderTarget(this.target);
		this.renderer.autoClear = false;
		this.renderer.setClearColor(0x000000, 0); // cleared pixels decode to pick-id 0 = no hit
		this.renderer.clear(true, true, false);
		this.renderer.render(this.scene, this.pickCamera);
		this.renderer.readRenderTargetPixels(this.target, 0, 0, boxPx, boxPx, this.buffer);
		this.letGo(n);
		this.renderer.setRenderTarget(prevTarget);
		this.renderer.autoClear = prevAutoClear;
		this.renderer.setClearColor(this.prevClear, prevClearAlpha);
		this.pickCamera.clearViewOffset();

		return this.decode(boxPx, r, rect, offsetX, offsetY);
	}

	/** Drop the objects of the last pick. A star node can leave its cache
	 *  before the next pick, and its geometry holds its whole payload. */
	private letGo(n: number): void {
		this.scene.clear();
		for (let i = 0; i < n; i++) {
			this.proxies[i].geometry = this.idleGeometry;
			this.proxies[i].material = this.material;
		}
		// The renderer holds its last list of a scene until it draws that scene
		// again. With autoClear off, this draws and clears no pixel.
		this.renderer.render(this.scene, this.pickCamera);
	}

	/** Decode the framebuffer box into distinct nearest-first candidates. */
	private decode(
		boxPx: number,
		r: number,
		rect: DOMRect,
		offsetX: number,
		offsetY: number
	): PickCandidate[] {
		const buf = this.buffer;
		const nearest = new Map<number, PickCandidate>();
		for (let py = 0; py < boxPx; py++) {
			// readRenderTargetPixels is bottom-origin; flip to top-origin CSS rows.
			const rowCss = boxPx - 1 - py;
			for (let px = 0; px < boxPx; px++) {
				const o = (py * boxPx + px) * 4;
				const pickId = (buf[o] | (buf[o + 1] << 8) | (buf[o + 2] << 16) | (buf[o + 3] << 24)) >>> 0;
				if (pickId === 0) continue;
				const dx = px - r;
				const dy = rowCss - r;
				const dist = Math.hypot(dx, dy);
				const prev = nearest.get(pickId);
				if (prev && prev.pixelDist <= dist) continue;
				// This lit pixel's centre back to NDC for the occlusion raycast.
				const cssX = offsetX + px + 0.5;
				const cssY = offsetY + rowCss + 0.5;
				nearest.set(pickId, {
					pickId,
					pixelDist: dist,
					ndcX: (cssX / rect.width) * 2 - 1,
					ndcY: -((cssY / rect.height) * 2 - 1)
				});
			}
		}
		return [...nearest.values()].sort((a, b) => a.pixelDist - b.pixelDist).slice(0, MAX_CANDIDATES);
	}

	dispose(): void {
		this.target.dispose();
		this.material.dispose();
		this.idleGeometry.dispose();
		this.proxies.length = 0;
	}
}
