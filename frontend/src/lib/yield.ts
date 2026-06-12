/** Yield to the event loop so input/rendering/timers can run between work
 *  slices. A MessageChannel macrotask rather than `scheduler.yield`: yield
 *  continuations would starve normal-priority tasks (fetch callbacks, the
 *  flush interval) for the whole ingest, and unlike `setTimeout` a message
 *  task has no nesting clamp. Standalone module so worker-shared code can
 *  import it without dragging UI dependencies into worker bundles. */
let yieldQueue: (() => void)[] | null = null;
let yieldPort: MessagePort | null = null;

export function yieldToMain(): Promise<void> {
	if (!yieldPort) {
		yieldQueue = [];
		const channel = new MessageChannel();
		channel.port1.onmessage = () => yieldQueue!.shift()?.();
		yieldPort = channel.port2;
	}
	return new Promise((resolve) => {
		yieldQueue!.push(resolve);
		yieldPort!.postMessage(null);
	});
}
