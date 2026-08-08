<script lang="ts" module>
	/** Night side of the lit disc — the lineup's and MoonDiscRow's own. */
	const SHADOW = '#05070e';

	/** `share` of `hex` mixed toward the night colour. Done here because an SVG
	 *  `stop-color` takes no `color-mix()`. */
	export function shadeToward(hex: string, share: number): string {
		const parse = (h: string) => {
			const v = h.replace('#', '');
			const full =
				v.length === 3
					? v
							.split('')
							.map((c) => c + c)
							.join('')
					: v;
			return [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16));
		};
		const [r, g, b] = parse(hex);
		const [nr, ng, nb] = parse(SHADOW);
		const mix = (a: number, n: number) => Math.round(a * share + n * (1 - share));
		return `rgb(${mix(r, nr)} ${mix(g, ng)} ${mix(b, nb)})`;
	}
</script>

<script lang="ts">
	/**
	 * A world cut open: the body as the rest of the app draws it, with the near
	 * half removed down to the Structure tab's own cross-section.
	 *
	 * Sized for a tile rather than for the panel, so it carries no labels, no
	 * scale and no temperatures — the collection page around it names the bodies
	 * and the body's own Structure tab has the rest. What it does keep is every
	 * rule the full cutaway draws by, because a tile that disagreed with the
	 * chart it links to would be worse than no tile.
	 */
	import { crossSection, type InteriorBand } from '$lib/charts/interior-cross-section';
	import { bandColor } from '$lib/charts/layer-appearance';
	import type { InteriorLayer } from '$lib/fetch/objects/object-data';

	interface Props {
		layers: InteriorLayer[];
		/** The body's own colour, for the half that is not cut away. */
		color: string;
		/** Roles the page is about — drawn with a floor on their thickness so a
		 *  thin one still reads. Empty means every layer is drawn to scale. */
		accent?: ReadonlySet<string>;
		/** Unique within the document: SVG gradients are referenced by id. */
		id: string;
		class?: string;
	}
	let { layers, color, accent, id, class: className = '' }: Props = $props();

	const R = 30;
	const C = 32;
	/** Floor on the accented layer's drawn thickness, in viewBox units. Europa's
	 *  ocean is 4.8% of its radius and rounds away at tile size; below this a
	 *  band is redrawn as an arc down its own middle, in its own colour, so a
	 *  thin ocean reads as a slightly thick one rather than as a marker over it. */
	const MIN_ACCENT = 2.4;

	let bands = $derived(crossSection(layers)?.bands ?? []);
	let sky = $derived(shadeToward(color, 0.55));

	function isAccent(band: InteriorBand): boolean {
		return accent?.has(band.layer.role) ?? false;
	}

	/** One band of the cut half — a wedge from the top of the disc to the bottom. */
	function halfBand(band: { outer: number; inner: number }): string {
		const ro = band.outer * R;
		const ri = band.inner * R;
		if (ri <= 0) return `M ${C} ${C} L ${C} ${C - ro} A ${ro} ${ro} 0 0 0 ${C} ${C + ro} Z`;
		return (
			`M ${C} ${C - ri} L ${C} ${C - ro} A ${ro} ${ro} 0 0 0 ${C} ${C + ro} ` +
			`L ${C} ${C + ri} A ${ri} ${ri} 0 0 1 ${C} ${C - ri} Z`
		);
	}

	/** The arc down the middle of a band, for the minimum-thickness redraw. */
	function midArc(band: { outer: number; inner: number }): string {
		const m = ((band.outer + band.inner) / 2) * R;
		return `M ${C} ${C - m} A ${m} ${m} 0 0 0 ${C} ${C + m}`;
	}
</script>

{#if bands.length}
	<svg viewBox="0 0 64 64" class={className} role="presentation">
		<defs>
			<radialGradient {id} cx="0.64" cy="0.3" r="0.86">
				<stop offset="0%" stop-color={color} />
				<stop offset="72%" stop-color={sky} />
				<stop offset="105%" stop-color={SHADOW} />
			</radialGradient>
			<!-- A diffuse layer has no surface — Jupiter's core is heavy elements
			     smeared through the envelope — so it fades into what is above it
			     rather than drawing a boundary its own source says is not there. -->
			{#each bands as band, i (i)}
				{#if band.layer.diffuse && i > 0}
					<radialGradient id="{id}-diffuse-{i}" gradientUnits="userSpaceOnUse" cx={C} cy={C} r={R}>
						<stop offset={(band.inner + band.outer) / 2} stop-color={bandColor(band, null)} />
						<stop offset={band.outer} stop-color={bandColor(band, null)} stop-opacity="0" />
					</radialGradient>
				{/if}
			{/each}
		</defs>

		<circle cx={C} cy={C} r={R} fill="url(#{id})" />

		{#each bands as band, i (i)}
			<!-- A band sitting on a diffuse one runs to the centre, so the fade has
			     something to dissolve into instead of the tile's background. -->
			{@const over = bands[i + 1]?.layer.diffuse === true}
			{@const fades = band.layer.diffuse && i > 0}
			<path
				d={halfBand(over ? { ...band, inner: 0 } : band)}
				fill={fades ? `url(#${id}-diffuse-${i})` : bandColor(band, null)}
			/>
		{/each}

		{#each bands as band, i (i)}
			{#if isAccent(band) && (band.outer - band.inner) * R < MIN_ACCENT}
				<path
					d={midArc(band)}
					fill="none"
					stroke={bandColor(band, null)}
					stroke-width={MIN_ACCENT}
				/>
			{/if}
		{/each}

		<!-- The cut itself. -->
		<path
			d="M {C} {C - R} L {C} {C + R}"
			fill="none"
			stroke="black"
			stroke-width="0.8"
			opacity="0.45"
		/>
	</svg>
{/if}
