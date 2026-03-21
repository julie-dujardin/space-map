<script lang="ts">
	import { Badge } from '$lib/components/ui/badge/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/object-data';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		fallbackName: string | null;
	}

	let { global, localized, fallbackName }: Props = $props();

	let name = $derived(localized?.name ?? global?.name ?? fallbackName ?? m.unknown());
	let image = $derived(localized?.wikipedia?.thumbnail ?? global?.wikidata?.image);
	let type = $derived(global?.type ?? m.object());
	let description = $derived(localized?.description ?? localized?.wikipedia?.description);
	let aliases = $derived(localized?.aliases);
</script>

<div class="flex flex-col gap-3">
	{#if image}
		<img src={image} alt={name} class="w-full max-h-48 object-cover rounded-md" />
	{/if}
	<div class="flex items-start gap-2">
		<h2 class="text-lg font-semibold leading-tight">{name}</h2>
		<Badge variant="secondary" class="shrink-0 text-xs">{type}</Badge>
	</div>
	{#if description}
		<p class="text-sm text-muted-foreground">{description}</p>
	{/if}
	{#if aliases && aliases.length > 0}
		<p class="text-xs text-muted-foreground">{m.also_known_as({ aliases: aliases.join(', ') })}</p>
	{/if}
</div>
