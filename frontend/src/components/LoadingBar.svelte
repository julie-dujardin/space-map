<script lang="ts">
	// Determinate when `value` (0..1) is given; otherwise an indeterminate sweep
	// for waits whose progress can't be measured (e.g. a full-page reload, where
	// the unloading page can't observe the fresh boot).
	let { value, label }: { value?: number; label?: string } = $props();
	const indeterminate = $derived(value === undefined);
</script>

<div
	class="h-1 w-56 max-w-[60vw] overflow-hidden rounded-full bg-text/10"
	role="progressbar"
	aria-label={label}
	aria-valuemin={0}
	aria-valuemax={100}
	aria-valuenow={indeterminate ? undefined : Math.round((value ?? 0) * 100)}
>
	{#if indeterminate}
		<div class="loadbar-sweep h-full w-2/5 rounded-full bg-text"></div>
	{:else}
		<div
			class="h-full rounded-full bg-text transition-[width] duration-300 ease-out"
			style="width: {(value ?? 0) * 100}%"
		></div>
	{/if}
</div>

<style>
	@keyframes loadbar-sweep {
		0% {
			transform: translateX(-110%);
		}
		100% {
			transform: translateX(360%);
		}
	}
	.loadbar-sweep {
		animation: loadbar-sweep 1.1s ease-in-out infinite;
	}
</style>
