<!-- An extrasolar object's values, grouped by meaning. -->
<script lang="ts">
	import Section from '../kit/Section.svelte';
	import StarRowList from './StarRowList.svelte';
	import type { StarSection } from './star-rows';

	interface Props {
		sections: StarSection[];
	}

	let { sections }: Props = $props();
</script>

{#each sections as section (section.key)}
	<Section title={section.title}>
		<StarRowList rows={section.rows} />
	</Section>
{/each}
