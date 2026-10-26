import { describe, expect, it, vi } from 'vitest';
import { PerspectiveCamera } from 'three';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import type { FocusState } from '$lib/scene/animation/focus';
import type { GpuPickPass } from './gpu-pick';
import type { PickRegistry } from './pick-registry';
import { PointerInteraction } from './pointer';

// The model loaders are not part of a click.
vi.mock('$lib/scene/objects/body/model', () => ({ attachedModelRoots: new Set() }));

/** Pointer events on an empty scene. Each pick that reaches the GPU pass logs
 *  its radius. */
function scene() {
	const canvas = Object.assign(new EventTarget(), {
		clientWidth: 800,
		clientHeight: 600,
		getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 })
	});
	const radii: number[] = [];
	const gpuPick = {
		pick: (...args: unknown[]) => {
			radii.push(args[5] as number);
			return [];
		}
	};
	const ctx = { bodies: { majorBodies: [] }, visibility: { systemShares: new Map() } };
	const pointer = new PointerInteraction(
		canvas as unknown as HTMLCanvasElement,
		new PerspectiveCamera(),
		ctx as unknown as ContextManager,
		{ jd: 0 } as SimClock,
		{ focusTruePos: [0, 0, 0] } as unknown as FocusState,
		[],
		new Map(),
		() => {},
		() => null,
		gpuPick as unknown as GpuPickPass,
		() => [],
		{} as PickRegistry,
		() => [],
		() => false
	);
	pointer.attach();
	const send = (type: string, x: number, y: number, init: Record<string, unknown> = {}): void => {
		const e = Object.assign(new Event(type), {
			pointerId: 1,
			isPrimary: true,
			pointerType: 'mouse',
			clientX: x,
			clientY: y,
			...init
		});
		canvas.dispatchEvent(e);
	};
	return { send, radii };
}

describe('PointerInteraction', () => {
	it('takes a mouse press that moves 3 px as a click', () => {
		const { send, radii } = scene();
		send('pointerdown', 100, 100);
		send('pointermove', 103, 100);
		send('pointerup', 102, 100);
		expect(radii).toEqual([24]);
	});

	it('takes a mouse press that moves 4 px as a drag, also when it comes back', () => {
		const { send, radii } = scene();
		send('pointerdown', 100, 100);
		send('pointermove', 104, 100);
		send('pointerup', 100, 100);
		expect(radii).toEqual([]);
	});

	it('takes a tap that wobbles 6 px as a click, with the wider radius', () => {
		const { send, radii } = scene();
		const touch = { pointerType: 'touch' };
		send('pointerdown', 100, 100, touch);
		send('pointermove', 105, 103, touch);
		send('pointerup', 101, 100, touch);
		expect(radii).toEqual([48]);
	});

	it('takes a finger that moves 11 px as a drag', () => {
		const { send, radii } = scene();
		const touch = { pointerType: 'touch' };
		send('pointerdown', 100, 100, touch);
		send('pointermove', 111, 100, touch);
		send('pointerup', 100, 100, touch);
		expect(radii).toEqual([]);
	});

	it('takes two fingers as a pinch, not a click', () => {
		const { send, radii } = scene();
		const touch = { pointerType: 'touch' };
		send('pointerdown', 100, 100, touch);
		send('pointerdown', 200, 100, { ...touch, pointerId: 2, isPrimary: false });
		send('pointerup', 200, 100, { ...touch, pointerId: 2, isPrimary: false });
		send('pointerup', 100, 100, touch);
		expect(radii).toEqual([]);
	});
});
