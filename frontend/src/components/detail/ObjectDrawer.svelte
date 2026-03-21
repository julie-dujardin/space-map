<script lang="ts">
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
	import { Button } from '$lib/components/ui/button/index.js';
	import XIcon from '@lucide/svelte/icons/x';
	import type { PositionedBody } from '$lib/types';
	import { fetchObjectDetail, type ObjectDetailData } from '$lib/object-data';
	import ObjectHeader from './ObjectHeader.svelte';
	import ObjectDescription from './ObjectDescription.svelte';
	import ObjectProperties from './ObjectProperties.svelte';
	import ObjectDiscovery from './ObjectDiscovery.svelte';
	import ObjectLinks from './ObjectLinks.svelte';

	interface Props {
		body: PositionedBody;
		onClose: () => void;
	}

	let { body, onClose }: Props = $props();

	let data = $state<ObjectDetailData | null>(null);
	let loading = $state(true);

	$effect(() => {
		const fileId = body.data.fileId;
		if (!fileId) return;
		loading = true;
		data = null;
		fetchObjectDetail(fileId).then((result) => {
			if (body.data.fileId === fileId) {
				data = result;
				loading = false;
			}
		});
	});
</script>

<aside
	class="fixed top-0 left-0 z-50 flex h-full w-[380px] max-w-[90vw] flex-col border-r bg-background shadow-lg overflow-y-auto max-md:inset-x-0 max-md:top-auto max-md:bottom-0 max-md:h-auto max-md:max-h-[70vh] max-md:w-full max-md:max-w-none max-md:rounded-t-xl max-md:border-t max-md:border-r-0"
>
	<div class="sticky top-0 z-10 flex justify-end p-2">
		<Button variant="ghost" size="icon-sm" onclick={onClose}>
			<XIcon />
			<span class="sr-only">Close</span>
		</Button>
	</div>

	<div class="px-4 pb-4 -mt-2">
		{#if loading}
			<div class="flex flex-col gap-4 p-1">
				<Skeleton class="w-full h-36 rounded-md" />
				<Skeleton class="w-3/4 h-6" />
				<Skeleton class="w-1/2 h-4" />
				<Skeleton class="w-full h-20" />
				<Skeleton class="w-full h-32" />
			</div>
		{:else}
			<div class="flex flex-col gap-5 p-1">
				<ObjectHeader
					global={data?.global ?? null}
					localized={data?.localized ?? null}
					fallbackName={body.data.name}
				/>
				<ObjectDescription extract={data?.localized?.wikipedia?.extract} />
				<ObjectProperties global={data?.global ?? null} />
				<ObjectDiscovery global={data?.global ?? null} localized={data?.localized ?? null} />
				<ObjectLinks global={data?.global ?? null} localized={data?.localized ?? null} />
			</div>
		{/if}
	</div>
</aside>
