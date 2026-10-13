import type { Material } from 'three';

/** A modifier's name. A function, where its shader depends on a setting that
 *  can change: a new name is a new program. */
type ShaderMod = string | (() => string);

interface TaggedMaterial extends Material {
	userData: { shaderMods?: ShaderMod[] };
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
export function tagShaderModifier(material: Material, mod: ShaderMod): void {
	const tagged = material as TaggedMaterial;
	const mods = (tagged.userData.shaderMods ??= []);
	if (mods.includes(mod)) return;
	mods.push(mod);
	material.customProgramCacheKey = () =>
		mods.map((name) => (typeof name === 'string' ? name : name())).join('|');
}

/**
 * Chain `patch` onto `material.onBeforeCompile`, tag the stack and request a
 * recompile. Every modifier goes through here so the cache key can never miss
 * one — the collision {@link tagShaderModifier} describes is silent.
 */
export function chainShaderHook(
	material: Material,
	mod: ShaderMod,
	patch: Material['onBeforeCompile']
): void {
	const prev = material.onBeforeCompile;
	material.onBeforeCompile = (shader, renderer) => {
		prev?.(shader, renderer);
		patch(shader, renderer);
	};
	tagShaderModifier(material, mod);
	material.needsUpdate = true;
}
