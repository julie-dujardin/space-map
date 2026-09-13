<!--
  The site mark, the drawing from static/favicon.svg. Inline rather than an
  <img> so it takes currentColor and follows the theme.

  The orbit carries more stroke than the favicon does: that file is drawn for a
  256px tab icon, and at the 22px this renders the original 8 lands under a
  pixel and greys out beside the wordmark.
-->
<script lang="ts">
	interface Props {
		class?: string;
	}

	let { class: className = 'size-[22px]' }: Props = $props();

	// The mask cuts the orbit where the moon crosses it; the id must not collide
	// with a second mark on the page.
	const uid = $props.id();
</script>

<svg
	viewBox="0 0 256 256"
	class="block shrink-0 {className}"
	fill="none"
	aria-hidden="true"
	focusable="false"
>
	<defs>
		<mask id="{uid}-gap">
			<rect width="256" height="256" fill="white" />
			<circle cx="228" cy="128" r="24" fill="black" />
		</mask>
	</defs>

	<circle cx="128" cy="128" r="30" fill="currentColor" />

	<g transform="rotate(-22 128 128)">
		<ellipse
			cx="128"
			cy="128"
			rx="100"
			ry="48"
			stroke="currentColor"
			stroke-width="12"
			fill="none"
			mask="url(#{uid}-gap)"
		/>
		<circle cx="228" cy="128" r="16" fill="currentColor" />
	</g>
</svg>
