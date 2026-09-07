<script lang="ts">
	// The overview hero's placeholder, in ObjectHeader's own geometry: the
	// picture at its 192px cap, the type badge, and the two lines of blurb
	// under it. Shared with the pre-chunk frame so the drawer that arrives is
	// the one already on screen.
	import { Skeleton } from '$lib/components/ui/skeleton/index.js';
</script>

<div class="flex flex-col gap-3 px-4 pt-1 pb-3" aria-hidden="true">
	<Skeleton class="h-48 w-full rounded-md" />
	<Skeleton class="h-5 w-24 rounded-full" />
	<div class="flex flex-col gap-2">
		<Skeleton class="h-4 w-full" />
		<Skeleton class="h-4 w-2/3" />
	</div>
</div>
