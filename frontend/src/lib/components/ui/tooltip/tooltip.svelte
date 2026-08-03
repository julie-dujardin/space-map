<script lang="ts">
	import { Tooltip as TooltipPrimitive } from 'bits-ui';

	// No provider here on purpose: one app-wide <Tooltip.Provider> in MapPage is
	// what makes opening a tooltip close the previous one and share the open
	// delay. A provider per root would put every tooltip in a group of one.
	let { open = $bindable(false), ...restProps }: TooltipPrimitive.RootProps = $props();
</script>

<TooltipPrimitive.Root bind:open {...restProps} />
