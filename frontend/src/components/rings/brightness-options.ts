/**
 * The two brightnesses a ring system can be rendered at.
 *
 * Every bundle stores its true intensity scale (e.g. 5.6e-6 at Jupiter), so
 * realistic rendering is correctly almost invisible. Overexposure drops that
 * scale and shows what the strip holds.
 */

import SunDimIcon from '@lucide/svelte/icons/sun-dim';
import SunIcon from '@lucide/svelte/icons/sun';
import * as m from '$lib/paraglide/messages.js';
import type { PillOption } from '../map-pill/pill-option';

export function ringBrightnessOptions(): PillOption<boolean>[] {
	return [
		{
			value: false,
			label: m.rings_brightness_realistic(),
			description: m.rings_brightness_realistic_desc(),
			Icon: SunDimIcon
		},
		{
			value: true,
			label: m.rings_brightness_overexposed(),
			description: m.rings_brightness_overexposed_desc(),
			Icon: SunIcon
		}
	];
}
