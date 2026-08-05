<script lang="ts">
	/**
	 * The Wikipedia lead for a section's topic — "Atmosphere of Mars" rather
	 * than "Mars" — set directly under the section title, above the chart it
	 * introduces.
	 *
	 * Half the object blurb's truncation: this opens a section rather than
	 * being one, and a full lead would push the chart off the panel.
	 */
	import type { TopicPage } from '$lib/fetch/objects/object-data';
	import ObjectDescription from '../ObjectDescription.svelte';

	interface Props {
		/** Absent for the locales with no article, which is most of them. */
		page?: TopicPage;
	}

	let { page }: Props = $props();
</script>

{#if page}
	<div class="my-2.5">
		<ObjectDescription extract={page.extract} wikipediaUrl={page.url} truncateLength={260} />
	</div>
{/if}
