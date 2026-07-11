<script lang="ts">
	import { cn, type WithElementRef } from '$lib/utils.js';
	import type { HTMLAttributes } from 'svelte/elements';

	let {
		ref = $bindable(null),
		class: className,
		children,
		...restProps
	}: WithElementRef<HTMLAttributes<HTMLElement>> = $props();
</script>

<!-- dir=ltr: month stepping is a fixed temporal axis, so prev/next stay
     left/right and their chevrons don't mirror in RTL. -->
<nav
	{...restProps}
	bind:this={ref}
	dir="ltr"
	class={cn('absolute inset-x-0 top-0 flex w-full items-center justify-between gap-1', className)}
>
	{@render children?.()}
</nav>
