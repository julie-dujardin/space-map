import { Color, ShaderMaterial, Vector3 } from 'three';

/**
 * Unlit Sun disc: adds Eddington limb darkening (I = 1 - u + u·μ, u ≈ 0.6) so
 * it reads as a sphere without a directional nightside. Orthographic camera
 * means every view ray is parallel to -Z, so μ is just the view-space normal's
 * z. Runs through the renderer's ACES + sRGB output like the lit bodies.
 */
export function makeLineupSunMaterial(colorHex: string): ShaderMaterial {
	const c = new Color(colorHex);
	return new ShaderMaterial({
		uniforms: { uColor: { value: new Vector3(c.r, c.g, c.b) } },
		vertexShader: `
			varying vec3 vNormalView;
			void main() {
				vNormalView = normalize(normalMatrix * normal);
				gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
			}
		`,
		fragmentShader: `
			uniform vec3 uColor;
			varying vec3 vNormalView;
			void main() {
				float mu = max(normalize(vNormalView).z, 0.0);
				float darkening = 1.0 - 0.6 + 0.6 * mu;
				gl_FragColor = vec4(uColor * darkening, 1.0);
				#include <tonemapping_fragment>
				#include <colorspace_fragment>
			}
		`
	});
}
