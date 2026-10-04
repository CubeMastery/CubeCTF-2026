import { MASK64, U64_MAX } from './config.js';

export function rotl64(value, bits) {
  return ((value << bits) | (value >> (64n - bits))) & MASK64;
}

export function fold(input) {
  let h = 0xcbf29ce484222325n;
  for (const byte of Buffer.from(String(input), 'utf8')) {
    h ^= BigInt(byte);
    h = (h * 0x100000001b3n) & MASK64;
    h ^= rotl64(h, 13n);
  }
  return h.toString(16).padStart(16, '0');
}

export function laneFor(slug) {
  return `ln${fold(slug).slice(0, 8)}`;
}

export function now() {
  return BigInt(Math.floor(Date.now() / 1000));
}

export function urlDecode(input) {
  const bytes = Buffer.from(input, 'latin1');
  const out = [];
  let i = 0;
  while (i < bytes.length) {
    const byte = bytes[i];
    if (byte === 0x2b) {
      out.push(0x20);
    } else if (byte === 0x25 && i + 2 < bytes.length) {
      const hex = bytes.toString('latin1', i + 1, i + 3);
      if (/^[0-9a-fA-F]{2}$/.test(hex)) {
        out.push(parseInt(hex, 16));
        i += 2;
      }
    } else {
      out.push(byte);
    }
    i += 1;
  }
  return Buffer.from(out).toString('latin1');
}

export function parseForm(input) {
  const form = new Map();
  for (const pair of String(input).split('&')) {
    if (pair === '') continue;
    const eq = pair.indexOf('=');
    const key = eq === -1 ? pair : pair.slice(0, eq);
    const value = eq === -1 ? '' : pair.slice(eq + 1);
    form.set(urlDecode(key), urlDecode(value));
  }
  return form;
}

export function clean(input) {
  return Array.from(String(input))
    .filter((c) => /[a-zA-Z0-9_-]/.test(c))
    .slice(0, 48)
    .join('')
    .toLowerCase();
}

export function escape(input) {
  return Array.from(String(input))
    .slice(0, 500)
    .map((c) => {
      switch (c) {
        case '\n':
        case '\r': return ' ';
        case '<': return '&lt;';
        case '>': return '&gt;';
        case '&': return '&amp;';
        default: return c;
      }
    })
    .join('');
}

export function formField(form, key) {
  return form.has(key) ? form.get(key) : undefined;
}

export function formDefault(form, key, fallback) {
  const value = formField(form, key);
  return value === undefined ? fallback : value;
}

export function parseU64(value) {
  if (typeof value !== 'string' || !/^\+?\d+$/.test(value)) return null;
  const parsed = BigInt(value);
  return parsed <= U64_MAX ? parsed : null;
}

export function toJson(value) {
  if (typeof value === 'bigint') return value.toString();
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(toJson).join(',')}]`;
  const entries = Object.entries(value)
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `${JSON.stringify(k)}:${toJson(v)}`);
  return `{${entries.join(',')}}`;
}
