import { describe, expect, it } from 'vitest';
import { Vector3 } from 'three';
import { surfaceSiteAt } from './surface-site';
import { bodyQuaternion } from '$lib/math/orientation';
import { bodyFixedUnit } from '$lib/scene/position/rendered-surface';
import { eclipticToScene } from '$lib/math/travel/state';
import { AU_KM, AU_SCALE } from '$lib/math/units';
import type { BodyData } from '$lib/types/objects';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';

/** The site callback against the renderer's own maths, so the drawn descent and
 *  the rendered feature label cannot disagree about where the ground is. */
describe('surfaceSiteAt', () => {
	const BODY = { id: 'naif-499', radiusKm: 3389.5 } as BodyData;
	const ORIENTATION = {
		pole_ra_0: 317.68,
		pole_ra_1: -0.106,
		pole_dec_0: 52.886,
		pole_dec_1: -0.0609,
		w0: 176.63,
		w1: 350.89198226,
		w2: 0
	};
	const DETAIL = { orientation: ORIENTATION } as GlobalObjectData;

	it('is the rendered surface point, in ecliptic axes', () => {
		const siteAt = surfaceSiteAt(BODY, DETAIL, -5.37, 137.81)!;
		const jd = 2461500.25;
		const site = siteAt(jd)!;

		// The renderer's placement: body-fixed unit, spun by the body quaternion,
		// in scene axes. The callback must be that point, only in ecliptic km.
		const unit = bodyFixedUnit(-5.37 * (Math.PI / 180), 137.81 * (Math.PI / 180));
		const rendered = new Vector3(unit[0], unit[1], unit[2])
			.applyQuaternion(bodyQuaternion(ORIENTATION, jd))
			.multiplyScalar(BODY.radiusKm * (AU_SCALE / AU_KM));
		const [x, y, z] = eclipticToScene(site);
		expect(x).toBeCloseTo(rendered.x, 12);
		expect(y).toBeCloseTo(rendered.y, 12);
		expect(z).toBeCloseTo(rendered.z, 12);
		expect(Math.hypot(...site)).toBeCloseTo(BODY.radiusKm, 9);
	});

	it('turns with the body', () => {
		const siteAt = surfaceSiteAt(BODY, DETAIL, 0, 0)!;
		const early = siteAt(2461500)!;
		// Half a Martian day later the equatorial site faces the other way — to
		// within the metres the pole itself precesses in half a day.
		const later = siteAt(2461500 + 0.5 * (360 / ORIENTATION.w1))!;
		expect(later[0]).toBeCloseTo(-early[0], 2);
		expect(later[1]).toBeCloseTo(-early[1], 2);
	});

	it('answers null without a spin model', () => {
		expect(surfaceSiteAt(BODY, {} as GlobalObjectData, 0, 0)).toBeNull();
		expect(surfaceSiteAt(BODY, null, 0, 0)).toBeNull();
	});
});
