import {
	AdditiveBlending,
	Box3,
	Mesh,
	MeshBasicMaterial,
	OrthographicCamera,
	PlaneGeometry,
	Scene,
	ShaderMaterial,
	Sphere,
	Vector2,
	type Object3D,
	type WebGLRenderer,
	WebGLRenderTarget
} from 'three';

const MASK_MIN = 64;
const MASK_MAX = 512;
// Fixed ±tap window; the gaussian sigma (never near this) shapes the falloff.
const BLUR_TAPS = 32;
// A blurred step only reaches 0.5 at the body edge, so the rim would read half as
// bright as a hand-drawn alpha-1.0 gradient — gain it back up before the clamp.
const RIM_GAIN = 2;

const BLUR_FRAG = /* glsl */ `
	uniform sampler2D tSrc;
	uniform vec2 uDir;   // per-tap uv step along the blur axis
	uniform float uSigma;
	uniform float uGain;
	varying vec2 vUv;
	void main() {
		float aSum = 0.0;
		float wSum = 0.0;
		for (int i = -${BLUR_TAPS}; i <= ${BLUR_TAPS}; i++) {
			float fi = float(i);
			float w = exp(-(fi * fi) / (2.0 * uSigma * uSigma));
			aSum += texture2D(tSrc, vUv + uDir * fi).a * w;
			wSum += w;
		}
		gl_FragColor = vec4(1.0, 1.0, 1.0, min(aSum / wSum * uGain, 1.0));
	}
`;

const FS_VERT = /* glsl */ `
	varying vec2 vUv;
	void main() {
		vUv = uv;
		gl_Position = vec4(position.xy, 0.0, 1.0);
	}
`;

/** Rim glow that hugs a body's true projected silhouette: a mask pass captures
 *  mesh coverage, a separable blur dilates it into a rim, and `plane` draws it
 *  additively just behind the body (depth masks the inner spread). Uses a real
 *  MeshBasicMaterial so the tint gets the scene's tone-map + sRGB output. Three
 *  offscreen passes, but only for the single hovered body. */
export class SilhouetteGlow {
	readonly plane: Mesh;

	private readonly glowPx: number;
	private readonly glowMat: MeshBasicMaterial;
	private readonly maskMat = new MeshBasicMaterial({ color: 0xffffff });
	private readonly maskCam = new OrthographicCamera(-1, 1, 1, -1, -1e6, 1e6);
	private readonly fsScene = new Scene();
	private readonly fsQuad: Mesh;
	private readonly blurMat: ShaderMaterial;

	private maskRt?: WebGLRenderTarget;
	private tmpRt?: WebGLRenderTarget;
	private glowRt?: WebGLRenderTarget;
	private rtSize = 0;
	private readonly box = new Box3();
	private readonly sphere = new Sphere();

	constructor(glowPx: number) {
		this.glowPx = glowPx;
		this.maskCam.position.z = 10;

		this.blurMat = new ShaderMaterial({
			uniforms: {
				tSrc: { value: null },
				uDir: { value: new Vector2() },
				uSigma: { value: 1 },
				uGain: { value: 1 }
			},
			vertexShader: FS_VERT,
			fragmentShader: BLUR_FRAG,
			depthTest: false,
			depthWrite: false
		});
		this.fsQuad = new Mesh(new PlaneGeometry(2, 2), this.blurMat);
		this.fsQuad.frustumCulled = false;
		this.fsScene.add(this.fsQuad);

		this.glowMat = new MeshBasicMaterial({
			transparent: true,
			blending: AdditiveBlending,
			depthWrite: false,
			opacity: 0
		});
		this.plane = new Mesh(new PlaneGeometry(1, 1), this.glowMat);
		this.plane.visible = false;
	}

	hide(): void {
		this.plane.visible = false;
	}

	/** Fade the frozen rim without re-rendering the mask (used on the way out). */
	setOpacity(opacity: number): void {
		this.glowMat.opacity = opacity;
		if (opacity === 0) this.plane.visible = false;
	}

	/** Capture `source`'s silhouette into a rim and point `plane` at it, depth
	 *  `z`. Frame sizes to the body's bounding sphere (+glowPx) so an elongated
	 *  asteroid's long axis never clips, and stays rotation-stable so a spinning
	 *  body doesn't shimmer the frame. */
	update(
		renderer: WebGLRenderer,
		scene: Scene,
		source: Object3D,
		z: number,
		tint: string,
		opacity: number
	): void {
		this.box.setFromObject(source);
		this.box.getBoundingSphere(this.sphere);
		const cx = this.sphere.center.x;
		const cy = this.sphere.center.y;
		const half = this.sphere.radius + this.glowPx;
		// A shape model with NaN vertices would poison the framing — bail, don't
		// build a NaN-sized target.
		if (!Number.isFinite(half) || !Number.isFinite(cx) || !Number.isFinite(cy)) {
			this.plane.visible = false;
			return;
		}

		const size = Math.max(MASK_MIN, Math.min(MASK_MAX, Math.round(2 * half)));
		this.ensureTargets(size);
		const maskRt = this.maskRt!;
		const tmpRt = this.tmpRt!;
		const glowRt = this.glowRt!;

		this.maskCam.left = cx - half;
		this.maskCam.right = cx + half;
		this.maskCam.top = cy + half;
		this.maskCam.bottom = cy - half;
		this.maskCam.updateProjectionMatrix();

		// Mask pass: only the body, flat white on transparent.
		const hidden: Object3D[] = [];
		for (const child of scene.children) {
			if (child !== source && child.visible) {
				child.visible = false;
				hidden.push(child);
			}
		}
		scene.overrideMaterial = this.maskMat;
		const prevTarget = renderer.getRenderTarget();
		renderer.setRenderTarget(maskRt);
		renderer.clear();
		renderer.render(scene, this.maskCam);
		scene.overrideMaterial = null;
		for (const child of hidden) child.visible = true;

		// Separable blur dilates the silhouette by ~glowPx screen px; sigma scales
		// with px-per-texel so the rim stays constant width on screen. Gain applies
		// once, on the final (vertical) pass.
		const sigma = (this.glowPx * size) / (2 * half) / 2.5 || 1;
		this.blurMat.uniforms.uSigma.value = sigma;

		this.blurMat.uniforms.uGain.value = 1;
		this.blurMat.uniforms.tSrc.value = maskRt.texture;
		(this.blurMat.uniforms.uDir.value as Vector2).set(1 / size, 0);
		renderer.setRenderTarget(tmpRt);
		renderer.render(this.fsScene, this.maskCam);

		this.blurMat.uniforms.uGain.value = RIM_GAIN;
		this.blurMat.uniforms.tSrc.value = tmpRt.texture;
		(this.blurMat.uniforms.uDir.value as Vector2).set(0, 1 / size);
		renderer.setRenderTarget(glowRt);
		renderer.render(this.fsScene, this.maskCam);

		renderer.setRenderTarget(prevTarget);

		if (this.glowMat.map !== glowRt.texture) {
			this.glowMat.map = glowRt.texture;
			this.glowMat.needsUpdate = true;
		}
		this.glowMat.color.set(tint);
		this.glowMat.opacity = opacity;
		this.plane.position.set(cx, cy, z);
		this.plane.scale.set(2 * half, 2 * half, 1);
		this.plane.visible = true;
	}

	private ensureTargets(size: number): void {
		if (size === this.rtSize && this.maskRt) return;
		this.maskRt?.dispose();
		this.tmpRt?.dispose();
		this.glowRt?.dispose();
		this.maskRt = new WebGLRenderTarget(size, size, { samples: 4 });
		this.tmpRt = new WebGLRenderTarget(size, size);
		this.glowRt = new WebGLRenderTarget(size, size);
		this.rtSize = size;
	}

	dispose(): void {
		this.maskRt?.dispose();
		this.tmpRt?.dispose();
		this.glowRt?.dispose();
		this.maskMat.dispose();
		this.blurMat.dispose();
		(this.fsQuad.geometry as PlaneGeometry).dispose();
		(this.plane.geometry as PlaneGeometry).dispose();
		this.glowMat.dispose();
	}
}
