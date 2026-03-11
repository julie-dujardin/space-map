<script lang="ts">
	import { T } from '@threlte/core';
	import { CanvasTexture } from 'three';

	interface Props {
		color: string;
		onclick?: () => void;
	}

	let { color, onclick }: Props = $props();

	function createRingTexture(col: string): CanvasTexture {
		const size = 128;
		const canvas = document.createElement('canvas');
		canvas.width = size;
		canvas.height = size;
		const ctx = canvas.getContext('2d')!;
		ctx.clearRect(0, 0, size, size);

		// Semi-transparent fill
		ctx.beginPath();
		ctx.arc(size / 2, size / 2, size / 2 - 8, 0, Math.PI * 2);
		ctx.fillStyle = col;
		ctx.globalAlpha = 0.15;
		ctx.fill();

		// Ring outline
		ctx.globalAlpha = 1;
		ctx.beginPath();
		ctx.arc(size / 2, size / 2, size / 2 - 8, 0, Math.PI * 2);
		ctx.strokeStyle = col;
		ctx.lineWidth = 4;
		ctx.stroke();

		return new CanvasTexture(canvas);
	}

	const texture = createRingTexture(color);
</script>

<T.Sprite scale={[0.03, 0.03, 1]} {onclick}>
	<T.SpriteMaterial map={texture} transparent sizeAttenuation={false} depthTest={false} />
</T.Sprite>
