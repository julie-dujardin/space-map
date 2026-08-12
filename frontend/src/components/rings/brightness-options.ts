/**
 * The two brightnesses a ring system can be rendered at, as the map chrome
 * offers them.
 *
 * Every bundle is stored normalised with its own intensity scale, so the true
 * one is the stored strip multiplied back down: at Jupiter that is a factor of
 * 5.6e-6, and the rings are correctly all but invisible. Overexposure drops the
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
