import { state } from '../state.js';
import { parseForm, formDefault, fold, now } from '../util.js';
import { jsonResponse, errorResponse } from '../response.js';
import { sessionUser, isAdmin, donationsWhere } from '../model.js';

export function orgArchive({ params, query, req }) {
  const mark = query.has('mark') ? query.get('mark') : '';
  const org = state.orgs.get(params.slug);
  if (!org) {
    return errorResponse(404, 'missing org');
  }
  if (fold(`${org.slug}:${org.owner}`) !== mark) {
    return errorResponse(403, 'archive unavailable');
  }
  return jsonResponse(200, { archive: donationsWhere((d) => d.org === params.slug) });
}

export function orgHandoff({ params, req }) {
  const username = sessionUser(req);
  if (username === null) {
    return errorResponse(401, 'login required');
  }
  if (!isAdmin(params.slug, username)) {
    return errorResponse(403, 'org admin required');
  }
  const stamp = now() / 60n;
  const proof = fold(`${username}:${stamp}`);
  state.handoffs.set(proof, username);
  return jsonResponse(200, { handoff: `${params.slug}.${stamp}.${proof}` });
}

export function acceptHandoff({ params, body, req }) {
  const form = parseForm(body);
  const username = sessionUser(req);
  if (username === null) {
    return errorResponse(401, 'login required');
  }
  const token = formDefault(form, 'handoff', '');
  const pieces = token.split('.');
  const stamp = pieces.length === 3 && /^\d+$/.test(pieces[1]) ? BigInt(pieces[1]) : null;
  if (stamp === null || now() / 60n > stamp + 4n) {
    return errorResponse(403, 'handoff expired');
  }
  if (!state.handoffs.has(pieces[2])) {
    return errorResponse(403, 'handoff unknown');
  }
  const org = state.orgs.get(params.slug);
  if (!org) {
    return errorResponse(404, 'missing org');
  }
  if (!org.admins.includes(username)) {
    org.admins.push(username);
  }
  return jsonResponse(200, { accepted: true });
}
