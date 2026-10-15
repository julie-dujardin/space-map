/**
 * Serves the WebGPU benchmark: the pages in this folder, and three from the
 * frontend's node_modules under /three/.
 *
 *   node scripts/webgpu-bench/serve.mjs   then open http://localhost:8123/
 */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const three = path.resolve(here, '../../node_modules/three');
const types = { '.js': 'text/javascript', '.mjs': 'text/javascript', '.html': 'text/html' };
const port = +(process.env.PORT ?? 8123);

http
	.createServer((req, res) => {
		let url = decodeURIComponent(req.url.split('?')[0]);
		if (url === '/') url = '/index.html';
		const file = url.startsWith('/three/')
			? path.join(three, url.slice('/three/'.length))
			: path.join(here, url);
		if (!file.startsWith(here) && !file.startsWith(three)) {
			res.writeHead(403).end();
			return;
		}
		fs.readFile(file, (err, data) => {
			if (err) {
				res.writeHead(404).end();
				return;
			}
			res.writeHead(200, {
				'content-type': types[path.extname(file)] ?? 'application/octet-stream'
			});
			res.end(data);
		});
	})
	.listen(port, () => console.log(`WebGPU bench on http://localhost:${port}/`));
