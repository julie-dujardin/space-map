# WebGPU benchmark

Compares three's `WebGLRenderer` (`webgl`) with `WebGPURenderer` on its WebGL2
backend (`webgpu-gl`) and on WebGPU (`webgpu`), on scenes shaped like Space Map's:

| Scene        | What it stands for                                                 |
| ------------ | ------------------------------------------------------------------ |
| `points`     | 1.5M asteroid points, 2 px, vertex colours, transparent            |
| `points-dyn` | the same, with every position rewritten and re-uploaded each frame |
| `drawcalls`  | 2,000 orbit lines + 400 lit spheres (~2,400 draws)                 |
| `fill`       | a full-screen 48-step march, in the shape of the atmosphere shell  |
| `bloom`      | 500 lines + 200 spheres + an HDR sun through bloom post-processing |

```sh
cd frontend
node scripts/webgpu-bench/serve.mjs
# open http://localhost:8123/ in Chrome and keep the tab in front
```

Query parameters on the runner: `w`, `h` (default 1920×1080), `frames` (60),
`reps` (3), `scens`, `modes` (comma lists). Every path draws into an offscreen
target of the same size, so no path pays for presenting and the comparison holds.

Columns: `update ms` is the scene's own JS per frame, `render() ms` the CPU time
inside the render call, `frame ms` the whole frame up to the GPU finishing it,
`lit %` a check that something was drawn. `webgl` bloom reads 0 % lit because its
composer keeps the result in its own buffers; the work is still done.

## First results: software rendering only (October 2026)

Run in a cloud container with no GPU (SwiftShader), 640×360, so the frame times
say nothing about a real GPU; the `render()` CPU times are the meaningful part.

- `points-dyn`: `render()` took 30–32 ms on WebGPU against 8–9 ms on WebGL — the
  18 MB per-frame upload is slower.
- `drawcalls`: within noise of each other (WebGL 14–17 ms, WebGPU 11.5–16 ms).
- First frame: 100–400 ms slower on `WebGPURenderer`.
- `webgpu-gl` bloom came back at ~6 ms a frame against ~180 ms elsewhere: three
  seems to skip the scene pass there, so that number is not valid.

Porting is the larger question: `WebGPURenderer` draws only node (TSL) materials,
and the app has ~3,200 lines of GLSL in 14 `ShaderMaterial`s and 17
`onBeforeCompile` patches.
