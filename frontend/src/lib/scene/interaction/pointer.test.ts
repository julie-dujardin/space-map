import { describe, expect, it, vi } from 'vitest';
import { PerspectiveCamera } from 'three';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { SimClock } from '$lib/scene/state/clock.svelte';
import type { FocusState } from '$lib/scene/animation/focus';
import type { GpuPickPass } from './gpu-pick';
import type { PickRegistry } from './pick-registry';
import { PointerInteraction } from './pointer';
import type { PositionedBody } from '$lib/types/objects';

// The model loaders are not part of a click.
vi.mock('$lib/scene/objects/body/model', () => ({ attachedModelRoots: new Set() }));

/** Pointer events on an empty scene. Each pick that reaches the GPU pass logs
 *  its radius. */
function scene({
	tapClaimed = () => false,
	tapPickDelay = () => 0,
	model = null
}: {
	tapClaimed?: (pointerId: number) => boolean;
	tapPickDelay?: (e: PointerEvent) => number;
	/** A body whose model covers the whole view: every tap hits it. */
	model?: PositionedBody | null;
} = {}) {
	const canvas = Object.assign(new EventTarget(), {
		clientWidth: 800,
		clientHeight: 600,
		getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 })
	});
	const radii: number[] = [];
	const picked: PositionedBody[] = [];
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
		(body) => picked.push(body),
		() => model,
		gpuPick as unknown as GpuPickPass,
		() => [],
		{} as PickRegistry,
		() => [],
		() => false,
		tapClaimed,
		tapPickDelay
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
	return { send, radii, picked };
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

	it('picks nothing on a tap the camera took as a zoom', () => {
		const { send, radii } = scene({ tapClaimed: (id) => id === 2 });
		const touch = { pointerType: 'touch' };
		send('pointerdown', 100, 100, touch);
		send('pointerup', 100, 100, touch);
		send('pointerdown', 100, 100, { ...touch, pointerId: 2 });
		send('pointerup', 100, 100, { ...touch, pointerId: 2 });
		expect(radii).toEqual([48]);
	});

	it('takes up a touch tap only once no second tap has come', () => {
		vi.useFakeTimers();
		try {
			const mars = { data: { id: 'mars' } } as PositionedBody;
			const { send, picked } = scene({ tapPickDelay: () => 300, model: mars });
			const touch = { pointerType: 'touch' };
			send('pointerdown', 100, 100, touch);
			send('pointerup', 100, 100, touch);
			vi.advanceTimersByTime(299);
			expect(picked).toEqual([]);
			vi.advanceTimersByTime(1);
			expect(picked).toEqual([mars]);
		} finally {
			vi.useRealTimers();
		}
	});

	it('drops a touch tap that a second made a double tap', () => {
		vi.useFakeTimers();
		try {
			const mars = { data: { id: 'mars' } } as PositionedBody;
			const { send, picked } = scene({
				tapClaimed: (id) => id === 2,
				tapPickDelay: () => 300,
				model: mars
			});
			const touch = { pointerType: 'touch' };
			send('pointerdown', 100, 100, touch);
			send('pointerup', 100, 100, touch);
			vi.advanceTimersByTime(100);
			send('pointerdown', 100, 100, { ...touch, pointerId: 2 });
			send('pointerup', 100, 100, { ...touch, pointerId: 2 });
			vi.advanceTimersByTime(1000);
			expect(picked).toEqual([]);
		} finally {
			vi.useRealTimers();
		}
	});

	it('takes up a tap at once where there is nothing to wait for', () => {
		const mars = { data: { id: 'mars' } } as PositionedBody;
		const { send, picked } = scene({ model: mars });
		send('pointerdown', 100, 100);
		send('pointerup', 100, 100);
		expect(picked).toEqual([mars]);
	});
});
