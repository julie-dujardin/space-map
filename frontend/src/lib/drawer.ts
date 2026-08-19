/**
 * Gap kept between a fully open mobile drawer and the top of the viewport.
 * Meets the collapsed search bar's top (pinned at top-4 = 16px), covering it
 * while leaving that same map sliver above. Shared so every drawer stops on
 * the same line.
 */
export const DRAWER_TOP_GAP_PX = 16;

/** The mobile sheet's top snap point for a given viewport height. Shared so
 *  the drawer's resize re-pin and the sheet's snap list can't disagree. */
export function topSnapPx(innerHeight: number): string {
	return `${Math.max(1, innerHeight - DRAWER_TOP_GAP_PX)}px`;
}
