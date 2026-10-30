/** The glyph and the colour a hazard is drawn with in the panel, once, so the
 *  row of trajectories and the detail below it cannot disagree. */

import FlameIcon from '@lucide/svelte/icons/flame';
import SolarPanelIcon from '@lucide/svelte/icons/solar-panel';
import EclipseIcon from '@lucide/svelte/icons/eclipse';
import RadioTowerIcon from '@lucide/svelte/icons/radio-tower';
import ShieldIcon from '@lucide/svelte/icons/shield';
import RadiationIcon from '@lucide/svelte/icons/radiation';
import OrbitIcon from '@lucide/svelte/icons/orbit';
import DnaOffIcon from '@lucide/svelte/icons/dna-off';
import CloudHailIcon from '@lucide/svelte/icons/cloud-hail';
import AtomIcon from '@lucide/svelte/icons/atom';
import { lethalDoseFraction } from '$lib/math/travel';
import type { Hazard, HazardKind, HazardSeverity } from '$lib/travel/hazards';

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
	// Orbit icon, not the radiation trefoil: a belt is a ring around a planet you
	// chose to pass, which the trefoil would just repeat from the row above.
	'belt-crossing': OrbitIcon,
	// The grains come from the interstellar cloud and strike the craft like hail.
	dust: CloudHailIcon,
	// Atoms, not the trefoil: the dose comes from the gas the craft runs into, and
	// the trefoil is already on the cosmic ray row.
	gas: AtomIcon
};

/** Past which a belt pass stops being a crossing to survive and becomes a dose
 *  nothing survives, in lethal doses. */
const UNSURVIVABLE_BELT_DOSES = 5;

/** The glyph for one hazard, except when the dose is off the scale its icon was
 *  chosen for — several lethal doses is not an orbit to plan around. */
export function hazardIcon(hazard: Hazard): typeof FlameIcon {
	if (
		hazard.kind === 'belt-crossing' &&
		!hazard.unpriced &&
		lethalDoseFraction(hazard.peak) > UNSURVIVABLE_BELT_DOSES
	) {
		return DnaOffIcon; // hehe
	}
	return HAZARD_ICONS[hazard.kind];
}

/**
 * Mid-palette, not themed tokens: the design system has no semantic warning
 * colour, and these three must stay distinguishable from each other and legible
 * on either ground. The map's own colours live in `$lib/travel/hazard-colors`;
 * here it's the panel agreeing with itself.
 */
export const HAZARD_TEXT: Record<HazardSeverity, string> = {
	notice: 'text-sky-500',
	caution: 'text-amber-500',
	severe: 'text-red-500'
};
