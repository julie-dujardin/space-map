/** The glyph and the colour a hazard is drawn with in the panel, once, so the
 *  row of trajectories and the detail below it cannot disagree. */

import FlameIcon from '@lucide/svelte/icons/flame';
import SolarPanelIcon from '@lucide/svelte/icons/solar-panel';
import EclipseIcon from '@lucide/svelte/icons/eclipse';
import RadioTowerIcon from '@lucide/svelte/icons/radio-tower';
import ShieldIcon from '@lucide/svelte/icons/shield';
import RadiationIcon from '@lucide/svelte/icons/radiation';
import OrbitIcon from '@lucide/svelte/icons/orbit';
import type { HazardKind, HazardSeverity } from '$lib/travel/hazards';

export const HAZARD_ICONS: Record<HazardKind, typeof FlameIcon> = {
	'solar-heat': FlameIcon,
	// The array, not a battery: what the distance costs is what the panels make,
	// and a craft out here may have no battery in the picture at all.
	'solar-power': SolarPanelIcon,
	conjunction: EclipseIcon,
	'signal-lag': RadioTowerIcon,
	// The hazard is the entry; what answers it is the shield.
	aeroassist: ShieldIcon,
	radiation: RadiationIcon,
	// The belt rather than the particles: what makes a crossing avoidable is that
	// it is a ring around a planet you chose to pass, which the trefoil does not
	// say and would anyway repeat the row above it.
	'belt-crossing': OrbitIcon
};

/**
 * Mid-palette rather than a themed token, and the same shade in both themes:
 * there is no semantic warning colour in the design system, and these three have
 * to stay distinguishable from each other as well as legible on either ground.
 * The map's own colours live in `$lib/travel/hazard-colors`, which is where the
 * arc and its chip agree; here it is the panel that has to agree with itself.
 */
export const HAZARD_TEXT: Record<HazardSeverity, string> = {
	notice: 'text-sky-500',
	caution: 'text-amber-500',
	severe: 'text-red-500'
};
