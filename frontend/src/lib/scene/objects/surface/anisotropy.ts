/** Anisotropy asked for on a map of a globe or a ring; three clamps it to the
 *  device's limit. Towards the limb a pixel covers many more map pixels along
 *  the view than across it, and on the map also east-west by 1 / cos φ. It
 *  has an effect only on a texture with a mipmap filter. */
export const MAX_ANISOTROPY = 16;
