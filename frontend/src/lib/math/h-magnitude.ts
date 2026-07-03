/** H-magnitude diameter estimate (Pravec & Harris 2007): D = 1329/√p_V · 10^(−H/5).
 *  ASSUMED_ALBEDO must match the ingest-side DAMIT model scaling (damit.py);
 *  the dark/bright bounds span typical asteroid albedos (MPC convention). */
export const ASSUMED_ALBEDO = 0.14;
export const DARK_ALBEDO = 0.05;
export const BRIGHT_ALBEDO = 0.25;

export function diameterKmFromH(h: number, albedo: number = ASSUMED_ALBEDO): number {
	return (1329 / Math.sqrt(albedo)) * 10 ** (-h / 5);
}
