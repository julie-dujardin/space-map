/**
 * Reactive calibration state. `progress` is non-null while a benchmark runs:
 * re-runs pause the map's render loop and show Scene's blur overlay; at boot
 * the map isn't mounted yet, so `bootPending` instead holds MapPage's loading
 * screen up until calibration settles — low-end devices never benchmark while
 * the live scene renders.
 */
export const calibrationUi = $state<{ progress: number | null; bootPending: boolean }>({
	progress: null,
	bootPending: false
});
