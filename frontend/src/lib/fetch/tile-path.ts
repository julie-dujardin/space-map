/**
 * Path of one tile inside its pyramid's folder (docs/export-format/tiles.md).
 * `cap` is empty for a tile of the map. Apart from the host's settings, so
 * that a worker can make tile URLs too.
 */
export function tilePath(cap: '' | 'north' | 'south', level: number, x: number, y: number): string {
	return `${cap && `${cap}/`}${level}/${x}/${y}.webp`;
}
