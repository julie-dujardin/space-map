import { SvelteMap } from 'svelte/reactivity';
import type { ModelCredit } from '$lib/scene/objects/body/model';

/** Credit of the mesh a lineup drew, by bundle slug. Read off the loaded GLB,
 *  so a credit bar names only what is on screen. */
export const lineupModelCredits = new SvelteMap<string, ModelCredit>();
