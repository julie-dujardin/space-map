<script lang="ts">
	// The tab bar's placeholder. Which tabs an object has is only known with its
	// payload, and a bar that appears late shoves the whole panel down, so the
	// row holds its 40px from the start.
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
</script>

<div class="pt-2" aria-hidden="true">
	<div class="flex w-full gap-4 border-b px-4 pb-2">
		<Skeleton class="h-4 w-14" />
		<Skeleton class="h-4 w-12" />
		<Skeleton class="h-4 w-16" />
	</div>
</div>
