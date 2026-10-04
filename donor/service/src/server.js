import http from 'node:http';
import { MAX_BODY } from './config.js';
import { route } from './routes.js';
import { textResponse } from './response.js';

const REASONS = {
  200: 'OK',
  400: 'Bad Request',
  401: 'Unauthorized',
  403: 'Forbidden',
  404: 'Not Found',
  409: 'Conflict',
};

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY) {
        reject(new Error('body too large'));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

export function createServer() {
  const server = http.createServer(async (req, res) => {
    let response;
    try {
      const body = await readBody(req);
      response = route(req, body);
    } catch {
      response = textResponse(400, 'bad request');
    }
    const reason = REASONS[response.status] ?? 'Error';
    res.sendDate = false;
    res.setHeader('Content-Type', response.contentType);
    res.setHeader('Content-Length', Buffer.byteLength(response.body));
    res.setHeader('Connection', 'close');
    for (const [key, value] of response.headers) {
      res.setHeader(key, value);
    }
    res.writeHead(response.status, reason);
    res.end(response.body);
  });

  server.on('clientError', (err, socket) => {
    if (!socket.writable) return;
    socket.end('HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 10\r\n\r\nbad request');
  });

  return server;
}
