<script lang="ts">
	import PaletteIcon from '@lucide/svelte/icons/palette';
	import * as Alert from '$lib/components/ui/alert/index.js';
	import { planetOfObjectId } from '$lib/fetch/extrasolar/ids';
	import { planetCatalogue } from '$lib/fetch/extrasolar/planets';
	import {
		impressionFacts,
		impressionText,
		type ImpressionFact
	} from '$lib/format/impression-facts';
	import * as m from '$lib/paraglide/messages.js';

	/** The warning while a sphere in view wears an artist's impression. It
	 *  speaks of the body `id`, and lists what its record measures. */
	interface Props {
		id: string;
	}

	let { id }: Props = $props();

	/** Null until the planet's record is read. */
	let facts = $state<ImpressionFact[] | null>(null);

	$effect(() => {
		const at = planetOfObjectId(id);
		let live = true;
		facts = null;
		if (!at) {
			facts = [];
			return;
		}
		planetCatalogue.planet(at.host, at.n).then(
			(found) => {
				if (!live) return;
				const host = found?.system.hosts.find((h) => h.id === found.planet.host);
				facts = found ? impressionFacts(found.planet, host) : [];
			},
			() => {
				if (live) facts = [];
			}
		);
		return () => {
			live = false;
		};
	});
</script>

{#if facts}
	<Alert.Root class="bg-card/95 text-start shadow-lg backdrop-blur">
		<PaletteIcon />
		<Alert.Title>{m.artist_impression_title()}</Alert.Title>
		<Alert.Description>{impressionText(facts)}</Alert.Description>
	</Alert.Root>
{/if}
