import { state } from './state.js';

export function sessionUser(req) {
  const cookie = req.headers.cookie;
  if (typeof cookie !== 'string') return null;
  for (const part of cookie.split(';')) {
    const trimmed = part.trim();
    if (trimmed.startsWith('sid=')) {
      return state.sessions.get(trimmed.slice(4)) ?? null;
    }
  }
  return null;
}

export function isAdmin(org, username) {
  const record = state.orgs.get(org);
  return record ? record.admins.includes(username) : false;
}

export function donationJson(donation) {
  return {
    id: donation.id,
    donor: donation.donor,
    org: donation.org,
    campaign: donation.campaign,
    amount: donation.amount,
    note: donation.note,
    receipt: donation.receipt,
    settled: donation.settled,
  };
}

export function donationsWhere(predicate) {
  return Array.from(state.donations.values()).filter(predicate).map(donationJson);
}
