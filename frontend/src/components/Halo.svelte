<script lang="ts">
	import { T, useTask } from '@threlte/core';
	import { CanvasTexture, type Sprite } from 'three';

	type HaloVariant = 'major' | 'minor' | 'spacecraft';

	interface Props {
		color: string;
		name: string;
		variant?: HaloVariant;
		onclick?: () => void;
	}

	let { color, name, variant = 'major', onclick }: Props = $props();

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

	function createMinorHaloTexture(): CanvasTexture {
		const size = 32;
		const canvas = document.createElement('canvas');
		canvas.width = size;
		canvas.height = size;
		const ctx = canvas.getContext('2d')!;
		ctx.beginPath();
		ctx.arc(size / 2, size / 2, size / 2 - 2, 0, Math.PI * 2);
		ctx.fillStyle = '#aaaaaa';
		ctx.globalAlpha = 0.3;
		ctx.fill();
		return new CanvasTexture(canvas);
	}

	function createSpacecraftHaloTexture(
		col: string,
		label: string
	): { texture: CanvasTexture; aspect: number; centerX: number } {
		const hexSize = 32;
		const labelFont = 'bold 10px sans-serif';
		const canvas = document.createElement('canvas');
		const ctx = canvas.getContext('2d')!;

		ctx.font = labelFont;
		const textWidth = ctx.measureText(label).width;
		const width = hexSize + 16 + textWidth + 16;
		const height = hexSize;
		canvas.width = width;
		canvas.height = height;

		const cx = hexSize / 2;
		const cy = height / 2;
		const r = hexSize / 2 - 8;

		// Draw hexagon path
		function hexPath() {
			ctx.beginPath();
			for (let k = 0; k < 6; k++) {
				const angle = (Math.PI / 3) * k - Math.PI / 6;
				const x = cx + r * Math.cos(angle);
				const y = cy + r * Math.sin(angle);
				if (k === 0) ctx.moveTo(x, y);
				else ctx.lineTo(x, y);
			}
			ctx.closePath();
		}

		// Hexagon: semi-transparent fill
		hexPath();
		ctx.fillStyle = col;
		ctx.globalAlpha = 0.15;
		ctx.fill();

		// Hexagon: outline
		ctx.globalAlpha = 1;
		hexPath();
		ctx.strokeStyle = col;
		ctx.lineWidth = 1;
		ctx.stroke();

		// Label text
		ctx.font = labelFont;
		ctx.fillStyle = 'white';
		ctx.shadowColor = 'black';
		ctx.shadowBlur = 6;
		ctx.textBaseline = 'middle';
		ctx.fillText(label, hexSize + 2, height / 2);

		const centerX = hexSize / 2 / width;
		return { texture: new CanvasTexture(canvas), aspect: width / height, centerX };
	}

	function createHalo(v: HaloVariant) {
		switch (v) {
			case 'minor':
				return { texture: createMinorHaloTexture(), aspect: 1, centerX: 0.5 };
			case 'spacecraft':
				return createSpacecraftHaloTexture(color, name);
			default:
				return createHaloTexture(color, name);
		}
	}

	const { texture, aspect, centerX } = createHalo(variant);
	const baseHeight = variant === 'minor' ? 0.012 : 0.03;
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
