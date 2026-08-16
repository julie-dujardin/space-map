import type { Material } from 'three';

interface TaggedMaterial extends Material {
	userData: { shaderMods?: string[] };
}

/**
 * Record that a shader modifier has been chained onto `material`, so three.js
 * can tell its program apart from another material's.
 *
 * three.js keys its global program cache on `onBeforeCompile.toString()`, but
 * our modifiers chain — the key only reflects the outermost hook, identical
 * for every material that helper touched. Without naming the whole stack, two
 * bodies ending in the same hook collide and whichever compiles first wins
 * silently (Mars once rendered with the Moon's shader, losing its sun tint).
 * Also keeps the key stable across detach/re-attach, since a cache hit skips
 * `onBeforeCompile` — and the uniform wiring with it.
 */
export function tagShaderModifier(material: Material, mod: string): void {
	const tagged = material as TaggedMaterial;
	const mods = (tagged.userData.shaderMods ??= []);
	if (mods.includes(mod)) return;
	mods.push(mod);
	material.customProgramCacheKey = () => mods.join('|');
}
