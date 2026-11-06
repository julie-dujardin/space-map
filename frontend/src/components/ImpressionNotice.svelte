<script lang="ts">
	import ChevronDownIcon from '@lucide/svelte/icons/chevron-down';
	import PaletteIcon from '@lucide/svelte/icons/palette';
	import * as Alert from '$lib/components/ui/alert/index.js';
	import * as Collapsible from '$lib/components/ui/collapsible/index.js';
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
		/** Show the title alone until a tap opens the text. For a phone, where
		 *  the full text covers the planet. */
		collapsible?: boolean;
	}

	let { id, collapsible = false }: Props = $props();

	/** Null until the planet's record is read. */
	let facts = $state<ImpressionFact[] | null>(null);
	let open = $state(false);

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

{#if facts && collapsible}
	<Collapsible.Root bind:open>
		<Alert.Root
			class="bg-card/95 p-0 text-start shadow-lg backdrop-blur {open ? '' : 'w-fit max-w-full'}"
		>
			<Collapsible.Trigger
				class="flex w-full min-w-0 items-center gap-2 rounded-lg px-2.5 py-2 text-start outline-none focus-visible:ring-2 focus-visible:ring-ring"
			>
				<PaletteIcon class="size-4 shrink-0" />
				<span class="min-w-0 flex-1 truncate font-medium">{m.artist_impression_title()}</span>
				<ChevronDownIcon
					class="size-4 shrink-0 text-muted-foreground transition-transform duration-200 {open
						? 'rotate-180'
						: ''}"
				/>
			</Collapsible.Trigger>
			<Collapsible.Content class="px-2.5 pb-2 ps-8.5">
				<Alert.Description>{impressionText(facts)}</Alert.Description>
			</Collapsible.Content>
		</Alert.Root>
	</Collapsible.Root>
{:else if facts}
	<Alert.Root class="bg-card/95 text-start shadow-lg backdrop-blur">
		<PaletteIcon />
		<Alert.Title>{m.artist_impression_title()}</Alert.Title>
		<Alert.Description>{impressionText(facts)}</Alert.Description>
	</Alert.Root>
{/if}
