import type { DirectionalLight, PointLight, Vector3 } from 'three';
import type { Vec3 } from '$lib/scene/animation/math';
import type { BodyObjects } from '$lib/scene/types';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import { AU_SCALE } from '$lib/math/units';

const LIGHT_DIST = 10;

/**
 * Swap the active sun light between the solar-system `PointLight` and the
 * sub-system `DirectionalLight`. The directional light points from the Sun's
 * focus-relative direction towards the origin, with the shadow camera sized
 * tightly to the current view distance for high texel density. When no
 * planetary system is active the directional light is silenced and the
 * point light at the Sun takes over.
 *
 * Rings no longer receive into the shadow map (their own shader ray-marches
 * the planet's oblate spheroid analytically), so the frustum can stay sized
 * to the camera view without a ring floor.
 */
export function updateSunShadowLight(
	bodyObjects: Map<string, BodyObjects>,
	focusTruePos: Vec3,
	ctx: ContextManager,
	shadowLight: DirectionalLight,
	sunPointLight: PointLight | undefined,
	cameraDistance: number,
	tmpV3: Vector3
): void {
	const sysId = ctx.activeSystemId;
	if (!sysId) {
		shadowLight.intensity = 0;
		if (sunPointLight) sunPointLight.intensity = 2;
		return;
	}

	const sunPos = bodyObjects.get('naif-10')?.body.position;
	const [fx, fy, fz] = focusTruePos;
	const sunRelX = (sunPos?.[0] ?? 0) - fx;
	const sunRelY = (sunPos?.[1] ?? 0) - fy;
	const sunRelZ = (sunPos?.[2] ?? 0) - fz;
	const sunDir = tmpV3.set(sunRelX, sunRelY, sunRelZ).normalize();

	shadowLight.position.copy(sunDir).multiplyScalar(LIGHT_DIST);
	shadowLight.target.position.set(0, 0, 0);
	shadowLight.intensity = 2;
	if (sunPointLight) sunPointLight.intensity = 0;

	const lateral = Math.max(cameraDistance * 2, 0.001);
	const depthExtent = ctx.getSystemExtent(sysId) * AU_SCALE * 1.2;
	const shadowCam = shadowLight.shadow.camera;
	shadowCam.left = shadowCam.bottom = -lateral;
	shadowCam.right = shadowCam.top = lateral;
	shadowCam.near = LIGHT_DIST - depthExtent;
	shadowCam.far = LIGHT_DIST + depthExtent;
	shadowCam.updateProjectionMatrix();
}
