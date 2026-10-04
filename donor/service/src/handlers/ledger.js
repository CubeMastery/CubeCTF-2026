import { state } from '../state.js';
import { clean, fold } from '../util.js';
import { jsonResponse, errorResponse } from '../response.js';
import { sessionUser, isAdmin, donationJson, donationsWhere } from '../model.js';

export function receiptView({ params, req }) {
  const user = sessionUser(req);
  for (const donation of state.donations.values()) {
    if (donation.receipt === params.receipt) {
      if (user === donation.donor || (user !== null && isAdmin(donation.org, user))) {
        return jsonResponse(200, donationJson(donation));
      }
      return errorResponse(403, 'receipt locked');
    }
  }
  return errorResponse(404, 'missing receipt');
}

export function ledgerWindow({ query }) {
  const org = clean(query.has('org') ? query.get('org') : '');
  const requestedLane = query.has('lane') ? query.get('lane') : '';
  const lane = requestedLane === '' ? '' : clean(requestedLane);
  const digest = query.has('digest') ? query.get('digest') : '';
  if (fold(`${org}:${lane}`) !== digest) {
    return errorResponse(403, 'window closed');
  }
  const entries = donationsWhere((d) => {
    const campaign = state.campaigns.get(d.campaign);
    return campaign ? campaign.org === org || campaign.lane === lane : false;
  });
  return jsonResponse(200, { entries });
}
