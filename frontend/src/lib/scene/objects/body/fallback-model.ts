import { BoxGeometry, CanvasTexture, Mesh, MeshStandardMaterial, SRGBColorSpace } from 'three';

/** Cuboid dimensions in metres for the "no model available yet" placeholder.
 *  Roughly the bounding box of a stowed cubesat-class spacecraft so the
 *  proportions read as spacecraft-like rather than as a generic box. The long
 *  axis is mapped to +Y so the cuboid stands upright relative to the camera's
 *  default up vector. The two largest faces (long × medium) carry the text. */
const SHORT = 0.38;
const MEDIUM = 1.52;
const LONG = 3.35;

const GRAY = 0x808080;
const TEXT_COLOR = '#1a1a1a';
const TEXT_LINES = ['no model', 'available yet'];

function makeTextTexture(): CanvasTexture {
	// Canvas aspect matches the upright LONG × MEDIUM face (portrait), so the
	// text isn't squished. Power-of-two-ish height keeps mipmaps happy without
	// burning memory.
	const ch = 1024;
	const cw = Math.round((ch * MEDIUM) / LONG);
	const canvas = document.createElement('canvas');
	canvas.width = cw;
	canvas.height = ch;
	const ctx = canvas.getContext('2d');
	if (!ctx) throw new Error('fallback-model: 2D canvas unavailable');
	ctx.fillStyle = `#${GRAY.toString(16).padStart(6, '0')}`;
	ctx.fillRect(0, 0, cw, ch);
	ctx.fillStyle = TEXT_COLOR;
	ctx.textAlign = 'center';
	ctx.textBaseline = 'middle';
	const fontPx = Math.round(cw * 0.13);
	ctx.font = `${fontPx}px system-ui, sans-serif`;
	const lineHeight = fontPx * 1.2;
	const blockTop = ch / 2 - ((TEXT_LINES.length - 1) * lineHeight) / 2;
	for (let i = 0; i < TEXT_LINES.length; i++) {
		ctx.fillText(TEXT_LINES[i], cw / 2, blockTop + i * lineHeight);
	}
	const tex = new CanvasTexture(canvas);
	tex.colorSpace = SRGBColorSpace;
	return tex;
}

/**
 * Build the placeholder cuboid shown in the model overlay for spacecraft that
 * have no GLB bundle. Returns a fresh mesh + materials + texture each call so
 * the existing GLB cleanup (which disposes everything it traverses) doesn't
 * affect other instances.
 */
export function buildFallbackSpacecraftModel(): Mesh {
	// Axes chosen so the LONG dimension is +Y (upright). Largest faces are
	// then ±X (LONG × MEDIUM).
	const geom = new BoxGeometry(SHORT, LONG, MEDIUM);
	const baseMat = new MeshStandardMaterial({ color: GRAY, roughness: 0.85, metalness: 0.05 });
	const textMat = new MeshStandardMaterial({
		color: GRAY,
		map: makeTextTexture(),
		roughness: 0.85,
		metalness: 0.05
	});
	// BoxGeometry material order: [+X, -X, +Y, -Y, +Z, -Z]. The two largest
	// faces are ±X; both get the text material — BoxGeometry's default UVs put
	// the texture upright when viewed from outside.
	const mesh = new Mesh(geom, [textMat, textMat, baseMat, baseMat, baseMat, baseMat]);
	mesh.castShadow = true;
	mesh.receiveShadow = true;
	return mesh;
}
