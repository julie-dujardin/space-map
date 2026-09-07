<script lang="ts">
	// The overview panel's placeholder, shaped like what lands: the stat-card
	// row, the Wikipedia extract (capped at 400 characters, so it comes out
	// about this tall wherever it is from), the cross-reference cards and one
	// section. A skeleton whose blocks sit elsewhere reads as a second reflow
	// when the real content replaces it.
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
</script>

<div class="flex flex-col gap-4" aria-hidden="true">
	<div class="grid auto-cols-fr grid-flow-col gap-2">
		<Skeleton class="h-[60px]" />
		<Skeleton class="h-[60px]" />
		<Skeleton class="h-[60px]" />
	</div>
	<Skeleton class="h-48 w-full" />
	<div class="grid grid-cols-2 gap-2">
		<Skeleton class="h-20" />
		<Skeleton class="h-20" />
	</div>
	<Skeleton class="h-28 w-full" />
</div>
