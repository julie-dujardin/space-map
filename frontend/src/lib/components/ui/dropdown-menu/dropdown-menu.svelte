<script lang="ts">
	import { DropdownMenu as DropdownMenuPrimitive } from 'bits-ui';
	import { getLocale, getTextDirection } from '$lib/paraglide/runtime.js';

	let {
		open = $bindable(false),
		// bits-ui defaults the menu to dir="ltr", which it stamps on the content:
		// an RTL locale's items un-mirror and `align` stops being logical.
		dir = getTextDirection(getLocale()),
		...restProps
	}: DropdownMenuPrimitive.RootProps = $props();
</script>

<DropdownMenuPrimitive.Root bind:open {dir} {...restProps} />
