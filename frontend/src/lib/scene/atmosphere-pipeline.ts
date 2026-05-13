/**
 * Off-screen post-processing pipeline for Earth's atmosphere — the full path
 * from Maxime Heckel's "On rendering realistic-looking skies, sunsets, and
 * planets"
 * (https://blog.maximeheckel.com/posts/on-rendering-the-sky-sunsets-and-planets/),
 * after Bruneton/Hillaire — with the LUTs traded for a brute-force per-pixel
 * raymarch (the atmosphere only ever covers a small slice of the screen).
 *
 * It stands up — and takes over the render — only while the camera is in the
 * Earth-Moon system. Everywhere else the renderer draws straight to the canvas
 * and the cheap additive limb-glow shell (`objects/atmosphere.ts`) is all that
 * runs; in the Earth-Moon system that shell is hidden and this pass does
 * everything it did *plus* aerial perspective (the surface seen through the
 * atmosphere gets attenuated and reddened toward the limb, instead of just
 * having glow added on top of it).
 *
 * Steps per frame:
 *  1. Scene → an HDR (HalfFloat) render target.
 *  2. A full-screen composition pass: reconstruct each pixel's world-space view
 *     ray, intersect it analytically with the planet sphere and the atmosphere
 *     shell, raymarch the slice between, then `out = sceneColour · transmittance
 *     + inscatter`, dimmed during eclipses, finally tone-mapped + sRGB-encoded
 *     to the canvas. (No depth buffer: Earth's surface is a smooth sphere here,
 *     so the analytic intersection *is* the surface — and that dodges the
 *     fragile depth-texture-on-HDR-target / MSAA-resolve plumbing.)
 *
 * Scattering math runs in planet-radius-normalised units (planet = unit sphere)
 * for float32 headroom, exactly like the shell shader; the ray geometry is done
 * in scene units and converted at the density lookups.
 *
 * Knobs (all in `ATMOSPHERE_PARAMS` — see `objects/atmosphere.ts`): `sunIntensity`
 * is shared with the shell, so tuning it there tunes both. `uStrength` here is a
 * 0..1 master fade for the whole composite (1 = full; 0 = plain scene, since the
 * shell is hidden in this mode). `PRIMARY_STEPS` / `LIGHT_STEPS` below trade
 * limb smoothness for full-screen fill cost — this pass marches every pixel the
 * atmosphere covers.
 */

import {
	ACESFilmicToneMapping,
	HalfFloatType,
	Matrix4,
	type PerspectiveCamera,
	type Scene,
	ShaderMaterial,
	Vector2,
	Vector3,
	type WebGLRenderer,
	WebGLRenderTarget
} from 'three';
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js';
import { type AtmosphereParams } from './objects/atmosphere';
import { getEclipseSceneUniforms, MAX_OCCLUDERS } from './objects/eclipse-shadow';

/**
 * Master switch for the Earth-Moon-system composition pipeline. Set to `false`
 * to fall back to drawing straight to the canvas (with the additive limb-glow
 * shell visible everywhere) — i.e. if the composite ever misbehaves, this is
 * the one-line escape to a known-good state.
 */
export const ATMOSPHERE_COMPOSITION_ENABLED = true;

/** Marching resolution for the composition pass. */
const PRIMARY_STEPS = 16;
const LIGHT_STEPS = 8;

const COMPOSITION_VERT = /* glsl */ `
	varying vec2 vUv;
	void main() {
		vUv = uv;
		gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
	}
`;

const COMPOSITION_FRAG = /* glsl */ `
	#define PRIMARY_STEPS ${PRIMARY_STEPS}
	#define LIGHT_STEPS ${LIGHT_STEPS}
	#define ECLIPSE_MAX_OCCLUDERS ${MAX_OCCLUDERS}
	#define PI 3.141592653589793

	uniform sampler2D tDiffuse;

	// View reconstruction. We rebuild the per-pixel ray from the FOV rather than
	// an inverse-projection matrix on purpose: this scene's near/far ratio (~1e15,
	// to feed the logarithmic depth buffer) blows the projection matrix's entries
	// up to ~1e9–1e12, so the small differences an inverse-projection unprojection
	// needs fall under float32 — w collapses to ~0 and the ray comes out NaN.
	uniform mat4 uCameraMatrixWorld;   // camera → world (focus-relative) frame
	uniform float uTanHalfFovY;        // tan(fovY / 2)
	uniform float uAspect;             // viewport width / height
	uniform vec3 uCameraPos;           // camera position, scene (focus-relative) frame

	// Atmosphere geometry (scene units, focus-relative frame)
	uniform vec3 uPlanetCenter;
	uniform float uPlanetRadiusScene;
	uniform float uAtmosphereRatio;    // (planet radius + atmosphere top) / planet radius

	// Atmosphere optics (β coefficients are per planet radius)
	uniform vec3 uSunDir;              // unit, Earth → Sun
	uniform vec3 uRayleighScatter;
	uniform float uRayleighScaleHeight;
	uniform float uMieScatter;
	uniform float uMieExtinction;
	uniform float uMieScaleHeight;
	uniform float uMieG;
	uniform vec3 uOzoneAbsorption;
	uniform float uOzoneCenter;
	uniform float uOzoneWidth;
	uniform float uSunIntensity;
	uniform vec3 uSunColor;
	uniform float uStrength;           // 0..1 master fade for the whole composite

	// Eclipse occlusion (shared scene-wide uniforms; see eclipse-shadow.ts)
	uniform float uSunAngularRadius;
	uniform int uOccluderCount;
	uniform vec4 uOccluders[ECLIPSE_MAX_OCCLUDERS];

	// Output
	uniform int uToneMap;              // 0 = none, 1 = ACES filmic
	uniform float uExposure;

	varying vec2 vUv;

	// Ray (origin ro, unit dir rd) vs sphere centred at origin, radius r.
	// Returns vec2(tNear, tFar); on a miss, (+huge, -huge).
	vec2 raySphere(vec3 ro, vec3 rd, float r) {
		float b = dot(ro, rd);
		float c = dot(ro, ro) - r * r;
		float d = b * b - c;
		if (d < 0.0) return vec2(1e9, -1e9);
		float s = sqrt(d);
		return vec2(-b - s, -b + s);
	}

	// Local (Rayleigh, Mie, ozone) densities at normalised altitude h.
	vec3 densities(float h) {
		return vec3(
			exp(-h / uRayleighScaleHeight),
			exp(-h / uMieScaleHeight),
			max(0.0, 1.0 - abs(h - uOzoneCenter) / uOzoneWidth)
		);
	}

	// Optical depth (Rayleigh, Mie, ozone), normalised units, from p (planet-
	// radius units, relative to the planet centre) toward the Sun to the top of
	// the atmosphere. Huge if the planet blocks the Sun.
	vec3 sunOpticalDepth(vec3 p) {
		if (raySphere(p, uSunDir, 1.0).x > 0.0) return vec3(1e6);
		float far = raySphere(p, uSunDir, uAtmosphereRatio).y;
		float dt = far / float(LIGHT_STEPS);
		vec3 od = vec3(0.0);
		for (int i = 0; i < LIGHT_STEPS; i++) {
			vec3 s = p + uSunDir * (dt * (float(i) + 0.5));
			od += densities(length(s) - 1.0) * dt;
		}
		return od;
	}

	// Fraction of the Sun's disc visible from worldPos (focus-relative frame),
	// skipping the body centred at selfPos. Mirrors eclipse-shadow.ts.
	float eclipseFactor(vec3 worldPos, vec3 selfPos) {
		if (uSunAngularRadius <= 0.0) return 1.0;
		float aSun = uSunAngularRadius;
		float result = 1.0;
		for (int i = 0; i < ECLIPSE_MAX_OCCLUDERS; i++) {
			if (i >= uOccluderCount) break;
			vec4 oc = uOccluders[i];
			float r = oc.w;
			if (r <= 0.0) continue;
			if (length(oc.xyz - selfPos) < r * 0.5) continue;
			vec3 toOc = oc.xyz - worldPos;
			float dOc = length(toOc);
			if (dOc < 1e-9) continue;
			float aOc = asin(min(r / dOc, 1.0));
			float sep = acos(clamp(dot(uSunDir, toOc) / dOc, -1.0, 1.0));
			if (aOc > 10.0 * aSun) {
				float t = (aOc - sep) / aSun;
				if (t >= 1.0) { result = 0.0; break; }
				if (t <= -1.0) continue;
				result *= 1.0 - (acos(-t) + t * sqrt(max(1.0 - t * t, 0.0))) / PI;
				continue;
			}
			if (sep >= aSun + aOc) continue;
			if (sep + aSun <= aOc) { result = 0.0; break; }
			if (sep + aOc <= aSun) { result *= 1.0 - (aOc * aOc) / (aSun * aSun); continue; }
			float a = aSun, b = aOc, c = sep;
			float x = (c * c + a * a - b * b) / (2.0 * c);
			float y = sqrt(max(a * a - x * x, 0.0));
			float A = a * a * acos(clamp(x / a, -1.0, 1.0))
				+ b * b * acos(clamp((c - x) / b, -1.0, 1.0)) - c * y;
			result *= 1.0 - A / (PI * a * a);
		}
		return result;
	}

	vec3 acesFilmic(vec3 x) {
		// Narkowicz fit, pre-scaled by 1/0.6 to line up with three's ACESFilmicToneMapping.
		x /= 0.6;
		return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
	}
	vec3 linearToSRGB(vec3 c) {
		return mix(1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, c * 12.92, vec3(lessThanEqual(c, vec3(0.0031308))));
	}
	vec4 present(vec3 linearColor) {
		vec3 c = linearColor;
		if (uToneMap == 1) c = acesFilmic(c * uExposure);
		else c = clamp(c, 0.0, 1.0);
		return vec4(linearToSRGB(max(c, 0.0)), 1.0);
	}

	void main() {
		vec3 sceneColor = texture2D(tDiffuse, vUv).rgb;

		// World-space view ray for this pixel, straight from the FOV (see note above).
		vec2 ndc = vUv * 2.0 - 1.0;
		vec3 rayDir = normalize(
			(uCameraMatrixWorld * vec4(ndc.x * uAspect * uTanHalfFovY, ndc.y * uTanHalfFovY, -1.0, 0.0)).xyz
		);

		// Analytic atmosphere slice along the ray, in scene units relative to the planet.
		vec3 ro = uCameraPos - uPlanetCenter;
		float atmoRadius = uPlanetRadiusScene * uAtmosphereRatio;
		vec2 atmoHit = raySphere(ro, rayDir, atmoRadius);
		// NaN-safe: testing !(x > y) early-outs on NaN too, so a bad ray can never paint the screen black.
		if (!(atmoHit.y > 0.0)) { gl_FragColor = present(sceneColor); return; } // misses the atmosphere

		vec2 planetHit = raySphere(ro, rayDir, uPlanetRadiusScene);
		float tStart = max(atmoHit.x, 0.0);
		float tEnd = atmoHit.y;
		if (planetHit.x > tStart && planetHit.x < tEnd) tEnd = planetHit.x; // stop at the surface
		if (!(tEnd > tStart)) { gl_FragColor = present(sceneColor); return; }

		float mu = dot(rayDir, uSunDir);
		float phaseR = (3.0 / (16.0 * PI)) * (1.0 + mu * mu);
		float g = uMieG;
		float phaseM = (3.0 / (8.0 * PI))
			* ((1.0 - g * g) * (1.0 + mu * mu))
			/ ((2.0 + g * g) * pow(max(1.0 + g * g - 2.0 * g * mu, 1e-4), 1.5));

		float dt = (tEnd - tStart) / float(PRIMARY_STEPS);          // scene units
		float dtNorm = dt / uPlanetRadiusScene;
		float invR = 1.0 / uPlanetRadiusScene;
		vec3 viewOD = vec3(0.0);   // optical depth, camera → current sample (normalised)
		vec3 inscR = vec3(0.0), inscM = vec3(0.0);

		for (int i = 0; i < PRIMARY_STEPS; i++) {
			vec3 pScene = ro + rayDir * (tStart + dt * (float(i) + 0.5));   // rel. planet centre
			vec3 pNorm = pScene * invR;
			vec3 dStep = densities(length(pNorm) - 1.0) * dtNorm;
			viewOD += dStep;
			vec3 totalOD = viewOD + sunOpticalDepth(pNorm);
			vec3 t = exp(-(uRayleighScatter * totalOD.x + uMieExtinction * totalOD.y + uOzoneAbsorption * totalOD.z));
			inscR += t * dStep.x;
			inscM += t * dStep.y;
		}

		// Transmittance camera → segment end (the surface, or the atmosphere exit).
		vec3 viewT = exp(-(uRayleighScatter * viewOD.x + uMieExtinction * viewOD.y + uOzoneAbsorption * viewOD.z));
		vec3 inscatter = uSunIntensity * uSunColor * (inscR * uRayleighScatter * phaseR + inscM * uMieScatter * phaseM);

		// Dim the in-scattered light during eclipses (evaluated once, at the segment midpoint).
		vec3 midWorld = uCameraPos + rayDir * (0.5 * (tStart + tEnd));
		inscatter *= eclipseFactor(midWorld, uPlanetCenter);

		vec3 composited = sceneColor * viewT + max(inscatter, 0.0);
		gl_FragColor = present(mix(sceneColor, composited, clamp(uStrength, 0.0, 1.0)));
	}
`;

export class AtmospherePipeline {
	private readonly renderer: WebGLRenderer;
	private readonly scene: Scene;
	private readonly camera: PerspectiveCamera;
	private readonly sceneTarget: WebGLRenderTarget;
	private readonly material: ShaderMaterial;
	private readonly quad: FullScreenQuad;

	/**
	 * @param planetRadiusScene  Earth's surface radius in scene units (post-flattening if applied).
	 * @param planetRadiusKm     Earth's surface radius in kilometres (for the per-radius coefficient conversion).
	 */
	constructor(
		renderer: WebGLRenderer,
		scene: Scene,
		camera: PerspectiveCamera,
		params: AtmosphereParams,
		planetRadiusScene: number,
		planetRadiusKm: number
	) {
		this.renderer = renderer;
		this.scene = scene;
		this.camera = camera;

		const dpr = renderer.getPixelRatio();
		const size = renderer.getSize(new Vector2());
		const w = Math.max(1, Math.round(size.width * dpr));
		const h = Math.max(1, Math.round(size.height * dpr));

		// HalfFloat so the in-scatter can exceed 1.0 before tone mapping. No depth
		// texture and no MSAA: the atmosphere geometry is analytic, so there's
		// nothing to read back, and that keeps this on the same plumbing Phase 2
		// verified. (Edge AA in the Earth-Moon view is therefore a TODO — FXAA in
		// this pass — rather than free.)
		this.sceneTarget = new WebGLRenderTarget(w, h, { type: HalfFloatType });
		this.sceneTarget.texture.name = 'AtmospherePipeline.scene';

		const ratio = 1 + params.topAltitudeKm / planetRadiusKm;
		const toNorm = (perKm: number) => perKm * planetRadiusKm;
		const r = params.rayleighScatterPerKm;
		const oz = params.ozoneAbsorptionPerKm;
		const c = params.sunColor;

		// Share the renderer-mutated occluder block by reference (so the per-frame
		// `updateEclipseUniforms` lands here), but NOT its `uSunDir` — that one is
		// the focus-origin→Sun direction every body's shadow shader reads, and we
		// mustn't overwrite it. The atmosphere uses its own Earth→Sun `uSunDir`.
		const eclipse = getEclipseSceneUniforms();

		this.material = new ShaderMaterial({
			uniforms: {
				uSunAngularRadius: eclipse.uSunAngularRadius,
				uOccluderCount: eclipse.uOccluderCount,
				uOccluders: eclipse.uOccluders,
				uSunDir: { value: new Vector3(1, 0, 0) },
				tDiffuse: { value: this.sceneTarget.texture },
				uCameraMatrixWorld: { value: new Matrix4() },
				uTanHalfFovY: { value: 1.0 },
				uAspect: { value: 1.0 },
				uCameraPos: { value: new Vector3() },
				uPlanetCenter: { value: new Vector3() },
				uPlanetRadiusScene: { value: planetRadiusScene },
				uAtmosphereRatio: { value: ratio },
				uRayleighScatter: { value: new Vector3(toNorm(r[0]), toNorm(r[1]), toNorm(r[2])) },
				uRayleighScaleHeight: { value: params.rayleighScaleHeightKm / planetRadiusKm },
				uMieScatter: { value: toNorm(params.mieScatterPerKm) },
				uMieExtinction: { value: toNorm(params.mieExtinctionPerKm) },
				uMieScaleHeight: { value: params.mieScaleHeightKm / planetRadiusKm },
				uMieG: { value: params.mieG },
				uOzoneAbsorption: { value: new Vector3(toNorm(oz[0]), toNorm(oz[1]), toNorm(oz[2])) },
				uOzoneCenter: { value: params.ozoneCenterKm / planetRadiusKm },
				uOzoneWidth: { value: params.ozoneWidthKm / planetRadiusKm },
				uSunIntensity: { value: params.sunIntensity },
				uSunColor: { value: new Vector3(c[0], c[1], c[2]) },
				uStrength: { value: 1.0 },
				uToneMap: { value: 0 },
				uExposure: { value: 1.0 }
			},
			vertexShader: COMPOSITION_VERT,
			fragmentShader: COMPOSITION_FRAG,
			depthTest: false,
			depthWrite: false
		});
		this.quad = new FullScreenQuad(this.material);
	}

	/**
	 * Render the scene through the atmosphere composite to the canvas.
	 * @param planetCenter  Earth's centre in the scene (focus-relative) frame.
	 * @param sunDir        Unit vector from Earth toward the Sun.
	 */
	render(planetCenter: Vector3, sunDir: Vector3): void {
		const cam = this.camera;
		const u = this.material.uniforms;

		// 1. Scene → off-screen HDR target.
		const prevTarget = this.renderer.getRenderTarget();
		this.renderer.setRenderTarget(this.sceneTarget);
		this.renderer.render(this.scene, cam);
		this.renderer.setRenderTarget(prevTarget);

		// 2. Per-frame uniforms (matrices are fresh after the render above).
		(u.uCameraMatrixWorld.value as Matrix4).copy(cam.matrixWorld);
		u.uTanHalfFovY.value = Math.tan((cam.fov * Math.PI) / 360); // fovY (deg) → tan(fovY / 2)
		u.uAspect.value = cam.aspect;
		(u.uCameraPos.value as Vector3).copy(cam.position);
		(u.uPlanetCenter.value as Vector3).copy(planetCenter);
		(u.uSunDir.value as Vector3).copy(sunDir).normalize();
		u.uToneMap.value = this.renderer.toneMapping === ACESFilmicToneMapping ? 1 : 0;
		u.uExposure.value = this.renderer.toneMappingExposure;

		// 3. Composite to the canvas.
		this.renderer.setRenderTarget(null);
		this.quad.render(this.renderer);
	}

	/** Master fade for the whole composite (0 = plain scene, 1 = full effect). */
	set strength(value: number) {
		this.material.uniforms.uStrength.value = value;
	}

	dispose(): void {
		this.sceneTarget.dispose();
		this.material.dispose();
		this.quad.dispose();
	}
}
