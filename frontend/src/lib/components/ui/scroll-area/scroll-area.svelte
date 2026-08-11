<script lang="ts">
	import { ScrollArea as ScrollAreaPrimitive } from 'bits-ui';
	import { getLocale, getTextDirection } from '$lib/paraglide/runtime.js';
	import { Scrollbar } from './index.js';
	import { cn, type WithoutChild } from '$lib/utils.js';

	let {
		ref = $bindable(null),
		// bits-ui defaults the root to dir="ltr", which resets the computed
		// direction for everything inside — an RTL locale's flex order and
		// logical properties silently un-mirror in every scroll area.
		dir = getTextDirection(getLocale()),
		viewportRef = $bindable(null),
		class: className,
		orientation = 'vertical',
		scrollbarXClasses = '',
		scrollbarYClasses = '',
		viewportClasses = '',
		children,
		...restProps
	}: WithoutChild<ScrollAreaPrimitive.RootProps> & {
		orientation?: 'vertical' | 'horizontal' | 'both' | undefined;
		scrollbarXClasses?: string | undefined;
		scrollbarYClasses?: string | undefined;
		/** For the viewport, not the root — a height cap only scrolls when it is
		 *  on the element that overflows. */
		viewportClasses?: string | undefined;
		viewportRef?: HTMLElement | null;
	} = $props();
</script>

<ScrollAreaPrimitive.Root
	bind:ref
	{dir}
	data-slot="scroll-area"
	class={cn('relative', className)}
	{...restProps}
>
	<ScrollAreaPrimitive.Viewport
		bind:ref={viewportRef}
		data-slot="scroll-area-viewport"
		class={cn(
			'cn-scroll-area-viewport focus-visible:ring-ring/50 size-full rounded-[inherit] transition-[color,box-shadow] outline-none focus-visible:ring-[3px] focus-visible:outline-1',
			viewportClasses
		)}
	>
		{@render children?.()}
	</ScrollAreaPrimitive.Viewport>
	{#if orientation === 'vertical' || orientation === 'both'}
		<Scrollbar orientation="vertical" class={scrollbarYClasses} />
	{/if}
	{#if orientation === 'horizontal' || orientation === 'both'}
		<Scrollbar orientation="horizontal" class={scrollbarXClasses} />
	{/if}
	<ScrollAreaPrimitive.Corner />
</ScrollAreaPrimitive.Root>
