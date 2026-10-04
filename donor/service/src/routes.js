import { jsonResponse, textResponse } from './response.js';
import { parseForm } from './util.js';
import { registerUser, registerOrg, login } from './handlers/auth.js';
import { createCampaign, showOrg, showCampaign } from './handlers/campaigns.js';
import { donationQuote, donationCommit, myDonations, orgDonations } from './handlers/donations.js';
import { orgArchive, orgHandoff, acceptHandoff } from './handlers/org.js';
import { routingTicket, routingSettle } from './handlers/routing.js';
import { receiptView, ledgerWindow } from './handlers/ledger.js';

const ROUTES = [
  ['GET', '/health', () => jsonResponse(200, { ok: true })],
  ['POST', '/api/register_user', registerUser],
  ['POST', '/api/register_org', registerOrg],
  ['POST', '/api/login', login],
  ['POST', '/api/campaigns', createCampaign],
  ['GET', '/api/orgs/:slug', showOrg],
  ['GET', '/api/campaigns/:campaign_id', showCampaign],
  ['POST', '/api/donations/quote', donationQuote],
  ['POST', '/api/donations/commit', donationCommit],
  ['GET', '/api/me/donations', myDonations],
  ['GET', '/api/orgs/:slug/donations', orgDonations],
  ['GET', '/api/orgs/:slug/archive', orgArchive],
  ['GET', '/api/orgs/:slug/handoff', orgHandoff],
  ['POST', '/api/orgs/:slug/handoff/accept', acceptHandoff],
  ['POST', '/api/routing/ticket', routingTicket],
  ['POST', '/api/routing/settle', routingSettle],
  ['GET', '/api/receipts/:receipt', receiptView],
  ['GET', '/api/ledger/window', ledgerWindow],
];

const COMPILED_ROUTES = ROUTES.map(([method, pattern, handler]) => ({
  method,
  parts: pattern.split('/').filter(Boolean),
  handler,
}));

export function matchRoute(method, path) {
  const parts = path.split('/').filter(Boolean);
  for (const route of COMPILED_ROUTES) {
    if (route.method !== method || route.parts.length !== parts.length) continue;
    const params = {};
    let matched = true;
    for (let i = 0; i < route.parts.length; i += 1) {
      const expected = route.parts[i];
      if (expected.startsWith(':')) {
        params[expected.slice(1)] = parts[i];
      } else if (expected !== parts[i]) {
        matched = false;
        break;
      }
    }
    if (matched) return { handler: route.handler, params };
  }
  return null;
}

export function route(req, body) {
  const raw = req.url || '/';
  const mark = raw.indexOf('?');
  const path = mark === -1 ? raw : raw.slice(0, mark);
  const query = parseForm(mark === -1 ? '' : raw.slice(mark + 1));
  const match = matchRoute(req.method, path);
  if (!match) {
    return textResponse(404, 'not found');
  }
  return match.handler({ req, params: match.params, query, body });
}
