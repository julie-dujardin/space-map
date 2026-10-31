/** The two ends of the clear-sky pill. On is the default, so it leads. */

import SatelliteIcon from '@lucide/svelte/icons/satellite';
import SparklesIcon from '@lucide/svelte/icons/sparkles';
import * as m from '$lib/paraglide/messages.js';
import type { PillOption } from '../map-pill/pill-option';

export function clearSkyOptions(): PillOption<boolean>[] {
	return [
		{
			value: true,
			label: m.layers_clear_sky_on(),
			description: m.layers_clear_sky_on_desc(),
			Icon: SparklesIcon
		},
		{
			value: false,
			label: m.layers_clear_sky_off(),
			description: m.layers_clear_sky_off_desc(),
			Icon: SatelliteIcon
		}
	];
}
