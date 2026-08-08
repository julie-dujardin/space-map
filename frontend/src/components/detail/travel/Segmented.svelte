<!-- Compact segmented control: the endpoint modes and the time-mode row. -->
<script lang="ts" generics="T extends string">
	interface Props {
		options: readonly { value: T; label: string }[];
		value: T;
		onchange: (value: T) => void;
		/** Shrink for use inside an endpoint box. */
		dense?: boolean;
		ariaLabel: string;
	}
	let { options, value, onchange, dense = false, ariaLabel }: Props = $props();
</script>

<div
	class="bg-muted/60 border-border/60 inline-flex w-full gap-0.5 rounded-md border p-0.5"
	role="group"
	aria-label={ariaLabel}
>
	{#each options as option (option.value)}
		<button
			type="button"
			aria-pressed={value === option.value}
			onclick={() => onchange(option.value)}
			class="flex-1 rounded-[5px] transition-colors {dense
				? 'px-1.5 py-0.5 text-[11px]'
				: 'px-2 py-1 text-xs'} {value === option.value
				? 'bg-background text-foreground shadow-sm'
				: 'text-muted-foreground hover:text-foreground'}"
		>
			{option.label}
		</button>
	{/each}
</div>
