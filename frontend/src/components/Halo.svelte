<script lang="ts">
	import { T } from '@threlte/core';
	import { CanvasTexture } from 'three';

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
		const ringSize = 128;
		const canvas = document.createElement('canvas');
		const ctx = canvas.getContext('2d')!;

		// Measure label to determine canvas width
		ctx.font = 'bold 36px sans-serif';
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
		ctx.font = 'bold 36px sans-serif';
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
	const spriteHeight = 0.03;
	const spriteWidth = spriteHeight * aspect;
	const center: [number, number] = [centerX, 0.5];
</script>

<T.Sprite scale={[spriteWidth, spriteHeight, 1]} {center} {onclick}>
	<T.SpriteMaterial map={texture} transparent sizeAttenuation={false} depthTest={false} />
</T.Sprite>
