import { toJson } from './util.js';

export function jsonResponse(status, payload) {
  return { status, contentType: 'application/json', body: toJson(payload), headers: [] };
}

export function textResponse(status, body) {
  return { status, contentType: 'text/plain; charset=utf-8', body, headers: [] };
}

export function errorResponse(status, message) {
  return jsonResponse(status, { error: message });
}
