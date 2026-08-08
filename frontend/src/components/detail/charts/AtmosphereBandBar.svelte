<script lang="ts">
	/** A body's air drawn edge-on across the full width, with no labels and no
	 *  scale — the tile backdrop for the Structure tab, in the layers and the
	 *  sky colour its cross-section uses. */

	import { atmosphereProfile } from '$lib/charts/atmosphere-cross-section';
	import { skyRgb } from '$lib/charts/layer-appearance';
	import type { AtmosphereStructure } from '$lib/fetch/objects/object-data';

	interface Props {
		/** The vertical stack, where anyone has named its boundaries. */
		structure?: AtmosphereStructure;
		/** What the air is mostly made of — the sky's colour, nothing else. */
		species?: { formula: string; share: number }[];
	}
	let { structure, species }: Props = $props();

	let bands = $derived(structure ? (atmosphereProfile(structure)?.bands ?? []) : []);
	let color = $derived(skyRgb(species));

	const W = 200;
	const H = 80;
	/** Apex of the surface, and a radius far past the frame so the limb reads as
	 *  a horizon rather than as a circle cropped by it. */
	const GROUND_Y = 70;
	const PLANET_R = 400;
	const CX = W / 2;
	const CY = GROUND_Y + PLANET_R;
	/** How much of the frame the air takes, above the apex. */
	const AIR = 64;

	/** Where the circle of radius `r` crosses this x. */
	function yAt(r: number, x: number): number {
		const dx = x - CX;
		return CY - Math.sqrt(Math.max(r * r - dx * dx, 0));
	}

	/** The shell between two heights, closed off the sides of the frame. */
	function shell(base: number, top: number): string {
		const inner = PLANET_R + base * AIR;
		const outer = PLANET_R + top * AIR;
		return [
			`M0,${yAt(outer, 0)}`,
			`A${outer},${outer} 0 0,1 ${W},${yAt(outer, W)}`,
			`L${W},${yAt(inner, W)}`,
			`A${inner},${inner} 0 0,0 0,${yAt(inner, 0)}`,
			'Z'
		].join(' ');
	}

	/** Stand-in stack for a body with no named boundaries: a smooth thinning,
	 *  drawn over the same height the scaled bodies use. */
	const FADE = Array.from({ length: 6 }, (_, i) => ({
		base: i / 6,
		top: (i + 1) / 6,
		opacity: 0.62 * (1 - i / 6) ** 1.6
	}));

	/** The body itself, from its limb down off the bottom of the frame. */
	const ground = [
		`M0,${H}`,
		`L0,${yAt(PLANET_R, 0)}`,
		`A${PLANET_R},${PLANET_R} 0 0,1 ${W},${yAt(PLANET_R, W)}`,
		`L${W},${H}`,
		'Z'
	].join(' ');
</script>

<!-- Its own near-black backdrop rather than the card's: the upper bands are
     nearly transparent, and on the light theme's muted grey they vanish. -->
<div class="size-full bg-[#05070e]">
	<svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" class="size-full" aria-hidden="true">
		{#each bands as band, i (i)}
			<path d={shell(band.base, band.top)} fill={color} opacity={band.opacity} />
		{/each}
		<!-- Half the atmospheres on the collection page have no named boundary
		     anywhere — the tenuous exospheres, and Mercury's and the Moon's. One
		     graded shell in the right colour is what can honestly be drawn for
		     them: it says there is air and what it looks like, and claims no
		     structure nobody has measured. -->
		{#if !bands.length}
			{#each FADE as step, i (i)}
				<path d={shell(step.base, step.top)} fill={color} opacity={step.opacity} />
			{/each}
		{/if}
		<!-- The body under its air: solid, so the stack sits on something rather
		     than fading out at the bottom of the frame. -->
		<path d={ground} fill="#10131c" />
	</svg>
</div>
