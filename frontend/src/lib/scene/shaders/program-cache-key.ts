import type { Material } from 'three';

interface TaggedMaterial extends Material {
	userData: { shaderMods?: string[] };
}

/**
 * Record that a shader modifier has been chained onto `material`, so three.js
 * can tell its program apart from another material's.
 *
 * three.js keys its (global) program cache on `onBeforeCompile.toString()`.
 * Our modifiers all chain — each wraps the previous hook — so the key only ever
 * reflects the *outermost* one, and its source text is identical for every
 * material that helper touched. Two bodies whose stacks end with the same
 * helper and whose map/define parameters agree therefore produce the same key,
 * and whichever compiles first wins: the Moon and Mars both end in the
 * self-shadow hook, so Mars silently rendered with the Moon's shader and lost
 * its atmospheric sun tint.
 *
 * Naming the whole stack fixes that. It also keeps a modifier's key stable
 * across a detach/re-attach cycle, which matters because a cache *hit* skips
 * `onBeforeCompile` — and with it the uniform wiring — entirely.
 */
export function tagShaderModifier(material: Material, mod: string): void {
	const tagged = material as TaggedMaterial;
	const mods = (tagged.userData.shaderMods ??= []);
	if (mods.includes(mod)) return;
	mods.push(mod);
	material.customProgramCacheKey = () => mods.join('|');
}
