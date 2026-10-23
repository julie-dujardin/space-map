/**
 * Where the skybox gives way to the starfield, by the camera's distance from
 * the barycentre. Inside the solar system the skybox is the sky, and the
 * starfield loads nothing. The skybox shows the sky from one point only, so
 * past the band the stars come from the catalogue.
 *
 * The band starts where the planetary system is small on screen. Neptune's
 * orbit is about 56 px across at 1,000 AU on a view 1080 px tall. The band
 * ends before the single viewpoint of the skybox shows. At 5,000 AU,
 * α Centauri is 1° off its place in the skybox.
 */

/** Past this distance (AU) the starfield loads, so its nearby nodes are in
 *  when the band starts. */
export const PREFETCH_AU = 500;
/** Back inside this distance (AU) the starfield stops loading. Below
 *  {@link PREFETCH_AU}, so a camera at the edge does not start and stop. */
export const RELEASE_AU = 400;
/** The crossfade, on a log scale of distance (AU). */
export const BAND_START_AU = 1_000;
export const BAND_END_AU = 5_000;

/** The starfield's share of the sky at this distance: 0 up to the band, 1
 *  past it. The skybox takes the rest. */
export function bandShare(distanceAu: number): number {
	const t = Math.log(distanceAu / BAND_START_AU) / Math.log(BAND_END_AU / BAND_START_AU);
	const c = Math.min(Math.max(t, 0), 1);
	return c * c * (3 - 2 * c);
}
