import { state, newId } from '../state.js';
import { parseForm, escape, formField, formDefault, parseU64, fold } from '../util.js';
import { jsonResponse, errorResponse } from '../response.js';
import { sessionUser, isAdmin, donationsWhere } from '../model.js';

export function donationQuote({ body, req }) {
  const form = parseForm(body);
  const username = sessionUser(req);
  if (username === null) {
    return errorResponse(401, 'login required');
  }
  const campaignId = formDefault(form, 'campaign', '');
  const amount = parseU64(formField(form, 'amount')) ?? 1n;
  const campaign = state.campaigns.get(campaignId);
  if (!campaign) {
    return errorResponse(404, 'missing campaign');
  }
  const scope = fold(`${username}:${campaign.lane}:${amount}`);
  const quote = `${campaignId}:${amount}:${campaign.lane}:${scope}`;
  return jsonResponse(200, { quote, org: campaign.org, lane: campaign.lane });
}

export function donationCommit({ body, req }) {
  const form = parseForm(body);
  const username = sessionUser(req);
  if (username === null) {
    return errorResponse(401, 'login required');
  }
  const quote = formDefault(form, 'quote', '');
  const parts = quote.split(':');
  const campaignId = parts[0] ?? '';
  const amount = parseU64(parts[1]) ?? 0n;
  const lane = parts[2] ?? '';
  const scope = parts[3] ?? '';
  if (fold(`${username}:${lane}:${amount}`) !== scope) {
    return errorResponse(403, 'quote expired');
  }
  const campaign = state.campaigns.get(campaignId);
  if (!campaign) {
    return errorResponse(404, 'missing campaign');
  }
  const note = escape(formDefault(form, 'note', ''));
  const receipt = fold(`${username}:${campaignId}:${note}`);
  const id = newId('d');
  state.donations.set(id, {
    id,
    donor: username,
    org: campaign.org,
    campaign: campaignId,
    amount,
    note,
    receipt,
    settled: false,
  });
  return jsonResponse(200, { donation: id, receipt });
}

export function myDonations({ req }) {
  const username = sessionUser(req);
  if (username === null) {
    return errorResponse(401, 'login required');
  }
  return jsonResponse(200, { donations: donationsWhere((d) => d.donor === username) });
}

export function orgDonations({ params, req }) {
  const username = sessionUser(req);
  if (username === null) {
    return errorResponse(401, 'login required');
  }
  if (!isAdmin(params.slug, username)) {
    return errorResponse(403, 'org admin required');
  }
  const org = state.orgs.get(params.slug);
  const vault = org ? org.vault : '';
  return jsonResponse(200, { vault, donations: donationsWhere((d) => d.org === params.slug) });
}
