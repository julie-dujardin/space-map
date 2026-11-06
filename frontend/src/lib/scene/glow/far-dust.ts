/**
 * The coarse dust past the nest's box (`docs/export-format/dust.md`, block
 * `far`): layer 4's shape about the Galactic centre, so the dust lane does not
 * stop where the Sun-centred nest ends. Only the glow reads it, and only where
 * no level of the nest holds the point, so nothing seen from the Sun changes.
 */

import { KIND_VOLUME } from '$lib/fetch/extrasolar/container';
import { fetchExtrasolarFile } from '$lib/fetch/extrasolar/files';
import type { LevelShape } from '$lib/scene/dust/march';
import {
	NestFormatError,
	fetchNestMetadata,
	type NestFarEntry,
	type NestTier
} from '$lib/scene/dust/nest';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import { glslFloat, glslVec3 } from '$lib/scene/dust/glsl';

export type FarDustEntry = NestFarEntry;

/** The volume in memory, R8 codes, x fastest. */
export interface FarDust {
	entry: FarDustEntry;
	size: Vec3;
	codes: Uint8Array;
}

function check(entry: FarDustEntry): void {
	const ok =
		entry.half_extent_pc.every((x) => x > 0) &&
		entry.floor > 0 &&
		entry.top > entry.floor &&
		(entry.z_map === 'asinh' ? entry.z_scale_pc > 0 : entry.z_map === 'linear');
	if (!ok) throw new NestFormatError('dust metadata.json: far');
}

/** The far dust of the nest that draws. */
export async function fetchFarDust(tier: NestTier): Promise<FarDust> {
	const meta = await fetchNestMetadata();
	// The glow loads only once the nest draws.
	if (!meta) throw new NestFormatError('dust metadata.json: no nest for the far dust');
	const entry = meta.far;
	check(entry);
	const file = entry[tier];
	const container = await fetchExtrasolarFile(file.path, meta.token, {
		prefix: 'dust',
		priority: 'low'
	});
	if (container.kind !== KIND_VOLUME) {
		throw new NestFormatError(`dust ${file.path}: kind ${container.kind}, not a volume`);
	}
	const codes = container.uint8('codes');
	if (codes.length !== file.size[0] * file.size[1] * file.size[2]) {
		throw new NestFormatError(`dust ${file.path}: texel count`);
	}
	return { entry, size: file.size, codes };
}

/**
 * GLSL of `glowDensity(p)`: the nest's density where a level holds `p`, else the
 * far dust's. Without far dust it is the nest's alone.
 */
export function glowDensityGlsl(levels: readonly LevelShape[], far: FarDustEntry | null): string {
	if (!far) return 'highp float glowDensity(highp vec3 p) { return density(p); }';
	const inNest = levels
		.map((level) => `all(lessThanEqual(a, ${glslVec3(level.half)}))`)
		.join(' || ');
	const [hx, hy, hz] = far.half_extent_pc;
	const w =
		far.z_map === 'asinh'
			? `asinh(g.z / ${glslFloat(far.z_scale_pc)}) * ${glslFloat(0.5 / Math.asinh(hz / far.z_scale_pc))}`
			: `g.z * ${glslFloat(0.5 / hz)}`;
	return /* glsl */ `
uniform highp sampler3D uFar;
highp float glowDensity(highp vec3 p) {
	highp vec3 a = abs(p);
	if (${inNest}) return density(p);
	highp vec3 g = p - ${glslVec3(far.centre_pc)};
	if (any(greaterThan(abs(g), ${glslVec3(far.half_extent_pc)}))) return 0.0;
	highp vec3 uvw = vec3(g.x * ${glslFloat(0.5 / hx)}, g.y * ${glslFloat(0.5 / hy)}, ${w}) + 0.5;
	return ${glslFloat(far.floor)} * (exp(textureLod(uFar, uvw, 0.0).r * ${glslFloat(Math.log1p(far.top / far.floor))}) - 1.0);
}
`;
}
