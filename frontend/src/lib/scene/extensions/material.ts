/**
 * The shader a host's filled area is drawn with.
 *
 * Vertices are placed relative to the camera rather than to the scene's
 * origin. A shape a few kilometres across, drawn an astronomical unit from the
 * render origin, has no float32 precision left for anything else — it would
 * shake apart as the camera moved. The scene's own orbit trails are drawn the
 * same way, and share the same rule: no depth writing, so a translucent area
 * never culls what is behind it.
 */

import { Color, DoubleSide, ShaderMaterial, Vector3 } from 'three';

export function makeAreaMaterial(color: string, opacity: number): ShaderMaterial {
	return new ShaderMaterial({
		transparent: true,
		depthWrite: false,
		// An area seen edge-on from behind is still the area the host drew.
		side: DoubleSide,
		uniforms: {
			uColor: { value: new Color(color) },
			uOpacity: { value: opacity },
			uCenterOffset: { value: new Vector3() }
		},
		vertexShader: `
			#include <common>
			#include <logdepthbuf_pars_vertex>
			uniform vec3 uCenterOffset;
			void main() {
				vec3 relPos = position + uCenterOffset;
				gl_Position = projectionMatrix * vec4(mat3(viewMatrix) * relPos, 1.0);
				#include <logdepthbuf_vertex>
			}
		`,
		fragmentShader: `
			#include <logdepthbuf_pars_fragment>
			uniform vec3 uColor;
			uniform float uOpacity;
			void main() {
				gl_FragColor = vec4(uColor, uOpacity);
				#include <logdepthbuf_fragment>
			}
		`
	});
}
