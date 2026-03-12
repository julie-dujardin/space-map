<script lang="ts">
	import { T, useTask } from '@threlte/core';
	import { CanvasTexture, type Sprite } from 'three';

	interface Props {
		color: string;
		name: string;
		onclick?: () => void;
	}

	let { color, name, onclick }: Props = $props();

	function createHaloTexture(
		col: string,
		label: string
	): { texture: CanvasTexture; aspect: number; centerX: number } {
		const ringSize = 96;
		const labelFont = 'bold 36px sans-serif';
		const canvas = document.createElement('canvas');
		const ctx = canvas.getContext('2d')!;

		// Measure label to determine canvas width
		ctx.font = labelFont;
		const textWidth = ctx.measureText(label).width;
		const width = ringSize + 16 + textWidth + 16;
		const height = ringSize;
		canvas.width = width;
		canvas.height = height;

		// Ring: semi-transparent fill
		const cx = ringSize / 2;
		const cy = height / 2;
		ctx.beginPath();
		ctx.arc(cx, cy, ringSize / 2 - 8, 0, Math.PI * 2);
		ctx.fillStyle = col;
		ctx.globalAlpha = 0.15;
		ctx.fill();

		// Ring: outline
		ctx.globalAlpha = 1;
		ctx.beginPath();
		ctx.arc(cx, cy, ringSize / 2 - 8, 0, Math.PI * 2);
		ctx.strokeStyle = col;
		ctx.lineWidth = 4;
		ctx.stroke();

		// Label text
		ctx.font = labelFont;
		ctx.fillStyle = 'white';
		ctx.shadowColor = 'black';
		ctx.shadowBlur = 6;
		ctx.textBaseline = 'middle';
		ctx.fillText(label, ringSize + 8, height / 2);

		// Sprite center anchored on the ring center (normalized 0–1 across canvas)
		const centerX = ringSize / 2 / width;

		return { texture: new CanvasTexture(canvas), aspect: width / height, centerX };
	}

	const { texture, aspect, centerX } = createHaloTexture(color, name);
	const baseHeight = 0.03;
	const hoverScale = 1.15;
	const center: [number, number] = [centerX, 0.5];

	let spriteRef = $state<Sprite>();
	let hovered = false;
	let currentScale = 1;

	useTask(() => {
		if (!spriteRef) return;
		const target = hovered ? hoverScale : 1;
		if (Math.abs(target - currentScale) > 0.001) {
			currentScale += (target - currentScale) * 0.15;
		} else {
			currentScale = target;
		}
		spriteRef.scale.set(baseHeight * aspect * currentScale, baseHeight * currentScale, 1);
	});

	function onpointerenter() {
		hovered = true;
		document.body.style.cursor = 'pointer';
	}

	function onpointerleave() {
		hovered = false;
		document.body.style.cursor = '';
	}
</script>

<T.Sprite
	bind:ref={spriteRef}
	scale={[baseHeight * aspect, baseHeight, 1]}
	{center}
	{onclick}
	{onpointerenter}
	{onpointerleave}
>
	<T.SpriteMaterial map={texture} transparent sizeAttenuation={false} depthTest={false} />
</T.Sprite>
