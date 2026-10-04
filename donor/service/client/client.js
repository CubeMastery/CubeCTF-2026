#!/usr/bin/env node
import http from 'node:http';
import readline from 'node:readline';

const DEFAULT_HOST = process.env.DONOR_HOST || '127.0.0.1';
const DEFAULT_PORT = Number(process.env.DONOR_PORT || 4739);

const C = {
  reset: '\x1b[0m',
  dim: '\x1b[2m',
  bold: '\x1b[1m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  grey: '\x1b[90m',
};

const FLAG_RE = /flag\{[^}]+\}/g;

class Client {
  constructor(host, port) {
    this.host = host;
    this.port = port;
    this.cookies = new Map();
    this.last = null;
  }

  request(method, path, fields = {}) {
    const body = new URLSearchParams(fields).toString();
    const headers = { 'Content-Type': 'application/x-www-form-urlencoded' };
    if (body) headers['Content-Length'] = Buffer.byteLength(body);
    const cookieHeader = Array.from(this.cookies.entries())
      .map(([k, v]) => `${k}=${v}`)
      .join('; ');
    if (cookieHeader) headers['Cookie'] = cookieHeader;

    return new Promise((resolve, reject) => {
      const req = http.request(
        { host: this.host, port: this.port, method, path, headers },
        (res) => {
          const chunks = [];
          res.on('data', (c) => chunks.push(c));
          res.on('end', () => {
            const text = Buffer.concat(chunks).toString('utf8');
            const setCookie = res.headers['set-cookie'];
            if (setCookie) {
              for (const line of setCookie) {
                const [pair] = line.split(';');
                const eq = pair.indexOf('=');
                if (eq > 0) this.cookies.set(pair.slice(0, eq).trim(), pair.slice(eq + 1).trim());
              }
            }
            this.last = { status: res.statusCode, headers: res.headers, text };
            resolve(this.last);
          });
        },
      );
      req.on('error', reject);
      if (body) req.write(body);
      req.end();
    });
  }

  get(path) {
    return this.request('GET', path);
  }

  post(path, fields) {
    return this.request('POST', path, fields);
  }
}

/* ------------------------------------------------------------------ output */

function colorize(text) {
  return text.replace(FLAG_RE, (m) => `${C.bold}${C.yellow}${m}${C.reset}`);
}

function pretty(text) {
  const trimmed = text.trim();
  if (!trimmed) return `${C.grey}(empty body)${C.reset}`;
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      return JSON.stringify(JSON.parse(trimmed), null, 2);
    } catch {
      return trimmed;
    }
  }
  return trimmed;
}

function show(result) {
  const { status, text } = result;
  const tone = status < 300 ? C.green : status < 500 ? C.yellow : C.red;
  console.log(`${C.grey}── ${tone}${status}${C.reset} ${C.dim}${result.headers['content-type'] || ''}${C.reset}`);
  console.log(colorize(pretty(text)));
  console.log();
}

/* ------------------------------------------------------------------- shell */

// Shell-style tokenizer: whitespace separates arguments, single/double quotes
// group values containing spaces, and backslash escapes the next character.
function tokenize(input) {
  const tokens = [];
  let current = '';
  let has = false;
  let quote = null;
  for (let i = 0; i < input.length; i += 1) {
    const ch = input[i];
    if (ch === '\\' && i + 1 < input.length) {
      current += input[i + 1];
      has = true;
      i += 1;
    } else if (quote) {
      if (ch === quote) {
        quote = null;
      } else {
        current += ch;
      }
    } else if (ch === '"' || ch === "'") {
      quote = ch;
      has = true;
    } else if (/\s/.test(ch)) {
      if (has) {
        tokens.push(current);
        current = '';
        has = false;
      }
    } else {
      current += ch;
      has = true;
    }
  }
  if (has) tokens.push(current);
  return tokens;
}

const COMMANDS = [
  { name: 'health', usage: 'health', run: (c) => c.get('/health') },
  { name: 'register_user', usage: 'register_user <username> <password> [display]', run: (c, a) => c.post('/api/register_user', { username: a[0], password: a[1], display: a[2] ?? a[0] }) },
  { name: 'register_org', usage: 'register_org <username> <password> <org_slug> [org_name] [vault]', run: (c, a) => c.post('/api/register_org', { username: a[0], password: a[1], org_slug: a[2], org_name: a[3] ?? a[2], vault: a[4] ?? '' }) },
  { name: 'login', usage: 'login <username> <password>', run: (c, a) => c.post('/api/login', { username: a[0], password: a[1] }) },
  { name: 'logout', usage: 'logout', run: (c) => { c.cookies.clear(); return Promise.resolve({ status: 200, headers: {}, text: 'session cleared' }); } },
  { name: 'whoami', usage: 'whoami', run: (c) => Promise.resolve({ status: 200, headers: {}, text: c.cookies.has('sid') ? `sid=${c.cookies.get('sid')}` : 'not logged in' }) },
  { name: 'campaigns', usage: 'campaigns <org> <title> [story] [goal] [lane]', run: (c, a) => c.post('/api/campaigns', { org: a[0], title: a[1], story: a[2] ?? '', goal: a[3] ?? '1000', lane: a[4] ?? '' }) },
  { name: 'org', usage: 'org <slug>', run: (c, a) => c.get(`/api/orgs/${encodeURIComponent(a[0])}`) },
  { name: 'campaign', usage: 'campaign <id>', run: (c, a) => c.get(`/api/campaigns/${encodeURIComponent(a[0])}`) },
  { name: 'quote', usage: 'quote <campaign> <amount>', run: (c, a) => c.post('/api/donations/quote', { campaign: a[0], amount: a[1] }) },
  { name: 'donate', usage: 'donate <quote> [note]', run: (c, a) => c.post('/api/donations/commit', { quote: a[0], note: a[1] ?? '' }) },
  { name: 'my_donations', usage: 'my_donations', run: (c) => c.get('/api/me/donations') },
  { name: 'org_donations', usage: 'org_donations <slug>', run: (c, a) => c.get(`/api/orgs/${encodeURIComponent(a[0])}/donations`) },
  { name: 'archive', usage: 'archive <slug> <mark>', run: (c, a) => c.get(`/api/orgs/${encodeURIComponent(a[0])}/archive?mark=${encodeURIComponent(a[1] ?? '')}`) },
  { name: 'handoff', usage: 'handoff <slug>', run: (c, a) => c.get(`/api/orgs/${encodeURIComponent(a[0])}/handoff`) },
  { name: 'accept_handoff', usage: 'accept_handoff <slug> <token>', run: (c, a) => c.post(`/api/orgs/${encodeURIComponent(a[0])}/handoff/accept`, { handoff: a[1] }) },
  { name: 'ticket', usage: 'ticket <org> [lane]', run: (c, a) => c.post('/api/routing/ticket', { org: a[0], lane: a[1] ?? '' }) },
  { name: 'settle', usage: 'settle <ticket> <donation>', run: (c, a) => c.post('/api/routing/settle', { ticket: a[0], donation: a[1] }) },
  { name: 'receipt', usage: 'receipt <receipt>', run: (c, a) => c.get(`/api/receipts/${encodeURIComponent(a[0])}`) },
  { name: 'ledger', usage: 'ledger <org> <lane> <digest>', run: (c, a) => c.get(`/api/ledger/window?org=${encodeURIComponent(a[0])}&lane=${encodeURIComponent(a[1] ?? '')}&digest=${encodeURIComponent(a[2] ?? '')}`) },
  { name: 'raw', usage: 'raw <METHOD> <path> [k=v ...]', run: (c, a) => {
      const fields = {};
      for (const kv of a.slice(2)) {
        const eq = kv.indexOf('=');
        if (eq > 0) fields[kv.slice(0, eq)] = kv.slice(eq + 1);
      }
      return c.request(a[0].toUpperCase(), a[1], fields);
    } },
  { name: 'target', usage: 'target [host] [port]', run: (c, a) => {
      if (a[0]) {
        c.host = a[0];
        if (a[1]) c.port = Number(a[1]);
      }
      return Promise.resolve({ status: 200, headers: {}, text: `target: ${c.host}:${c.port}` });
    } },
  { name: 'help', usage: 'help [command]', run: (c, a) => {
      if (a[0]) {
        const cmd = COMMANDS.find((x) => x.name === a[0]);
        return Promise.resolve({ status: 200, headers: {}, text: cmd ? `${cmd.usage}\n\n${cmd.desc || ''}` : `unknown command: ${a[0]}` });
      }
      const rows = COMMANDS.map((x) => `  ${C.cyan}${x.name.padEnd(16)}${C.reset} ${C.dim}${x.usage}${C.reset}`);
      return Promise.resolve({ status: 200, headers: {}, text: rows.join('\n') });
    } },
];

for (const cmd of COMMANDS) {
  cmd.desc = cmd.desc || '';
}
COMMANDS.find((c) => c.name === 'register_user').desc = 'Create a donor account.';
COMMANDS.find((c) => c.name === 'register_org').desc = 'Create an organization owned by a new admin user.';
COMMANDS.find((c) => c.name === 'login').desc = 'Log in; the session cookie is stored and reused automatically.';
COMMANDS.find((c) => c.name === 'campaigns').desc = 'Create a campaign (org admin only).';
COMMANDS.find((c) => c.name === 'quote').desc = 'Get a signed donation quote for a campaign.';
COMMANDS.find((c) => c.name === 'donate').desc = 'Commit a donation using a quote; the note is private.';
COMMANDS.find((c) => c.name === 'archive').desc = 'Read an org archive using a mark derived from public data.';
COMMANDS.find((c) => c.name === 'handoff').desc = 'Mint an org admin handoff token (org admin only).';
COMMANDS.find((c) => c.name === 'accept_handoff').desc = 'Accept a handoff token to gain admin on an org.';
COMMANDS.find((c) => c.name === 'ticket').desc = 'Get a routing ticket for an org lane (org admin only).';
COMMANDS.find((c) => c.name === 'settle').desc = 'Settle a donation into a routing lane (org admin only).';
COMMANDS.find((c) => c.name === 'ledger').desc = 'Read the ledger window for an org/lane using a digest.';
COMMANDS.find((c) => c.name === 'raw').desc = 'Send an arbitrary request, e.g. raw POST /api/login username=a password=b';
COMMANDS.find((c) => c.name === 'target').desc = 'Show or change the host/port the client talks to.';
COMMANDS.find((c) => c.name === 'help').desc = 'List commands or show usage for one command.';

const BANNER = `
${C.bold}Donor${C.reset} ${C.dim}donation desk client${C.reset}
  target ${C.cyan}${DEFAULT_HOST}:${DEFAULT_PORT}${C.reset}   ${C.dim}(set with: target <host> <port>)${C.reset}
  ${C.dim}type ${C.reset}${C.cyan}help${C.reset}${C.dim} for commands, ${C.reset}${C.cyan}exit${C.reset}${C.dim} to quit${C.reset}
`;

const PROMPT = `${C.green}donor>${C.reset} `;

async function main() {
  const [host, portArg] = process.argv.slice(2);
  const client = new Client(host || DEFAULT_HOST, portArg ? Number(portArg) : DEFAULT_PORT);
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout, prompt: '' });

  const writePrompt = () => process.stdout.write(PROMPT);
  const writeLine = (text = '') => process.stdout.write(`${text}\n`);

  console.log(BANNER);
  writePrompt();

  // Serialise handling so output never interleaves with the prompt, and so
  // piped input is processed one line at a time in order.
  let queue = Promise.resolve();
  rl.on('line', (line) => {
    queue = queue.then(async () => {
      const input = line.trim();
      if (!input) {
        writePrompt();
        return;
      }
      const tokens = tokenize(input);
      const [name, ...args] = tokens;
      const cmd = COMMANDS.find((c) => c.name === name);
      if (!cmd) {
        writeLine(`${C.red}unknown command:${C.reset} ${name}  ${C.dim}(type ${C.reset}${C.cyan}help${C.reset}${C.dim})${C.reset}`);
        writePrompt();
        return;
      }
      try {
        const result = await cmd.run(client, args);
        show(result);
      } catch (err) {
        writeLine(`${C.red}error:${C.reset} ${err.message}`);
        writeLine();
      }
      writePrompt();
    });
  });

  // Do not exit here: with piped input stdin reaches EOF while a request is
  // still in flight, and exiting would truncate the output. Once the queue
  // drains there is nothing left holding the event loop open, so the process
  // exits naturally.
  rl.on('close', () => {
    writeLine();
  });
}

main();
