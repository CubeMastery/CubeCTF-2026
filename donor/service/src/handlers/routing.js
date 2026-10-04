import { state } from '../state.js';
import { parseForm, clean, formField, formDefault, fold, laneFor } from '../util.js';
import { jsonResponse, errorResponse } from '../response.js';
import { sessionUser, isAdmin } from '../model.js';

export function routingTicket({ body, req }) {
  const form = parseForm(body);
  const username = sessionUser(req);
  if (username === null) {
    return errorResponse(401, 'login required');
  }
  const org = clean(formDefault(form, 'org', ''));
  if (!isAdmin(org, username)) {
    return errorResponse(403, 'org admin required');
  }
  const requestedLane = formField(form, 'lane');
  const lane = requestedLane === undefined ? '' : clean(requestedLane);
  const assignedLane = lane === '' ? laneFor(org) : lane;
  const ticket = `${org}:${assignedLane}:${fold(`${username}:${assignedLane}`)}`;
  return jsonResponse(200, { ticket });
}

export function routingSettle({ body, req }) {
  const form = parseForm(body);
  const username = sessionUser(req);
  if (username === null) {
    return errorResponse(401, 'login required');
  }
  const ticket = formDefault(form, 'ticket', '');
  const donationId = formDefault(form, 'donation', '');
  const pieces = ticket.split(':');
  if (pieces.length !== 3 || fold(`${username}:${pieces[1]}`) !== pieces[2]) {
    return errorResponse(403, 'ticket rejected');
  }
  if (!isAdmin(pieces[0], username)) {
    return errorResponse(403, 'org admin required');
  }
  const donation = state.donations.get(donationId);
  if (!donation) {
    return errorResponse(404, 'missing donation');
  }
  const campaign = state.campaigns.get(donation.campaign);
  const campaignLane = campaign ? campaign.lane : '';
  if (campaignLane !== pieces[1]) {
    return errorResponse(409, 'routing lane mismatch');
  }
  donation.org = pieces[0];
  donation.settled = true;
  return jsonResponse(200, { moved: donation.id });
}
