import { state, newId } from '../state.js';
import { parseForm, clean, escape, formField, formDefault, parseU64, laneFor } from '../util.js';
import { jsonResponse, errorResponse } from '../response.js';
import { sessionUser, isAdmin } from '../model.js';

export function createCampaign({ body, req }) {
  const form = parseForm(body);
  const username = sessionUser(req);
  if (username === null) {
    return errorResponse(401, 'login required');
  }
  const org = clean(formDefault(form, 'org', ''));
  if (!isAdmin(org, username)) {
    return errorResponse(403, 'org admin required');
  }
  const title = escape(formDefault(form, 'title', 'Community need'));
  const story = escape(formDefault(form, 'story', ''));
  const goal = parseU64(formField(form, 'goal')) ?? 1000n;
  const requestedLane = formField(form, 'lane');
  const lane = requestedLane === undefined ? '' : clean(requestedLane);
  const assignedLane = lane === '' ? laneFor(org) : lane;
  const id = newId('c');
  state.campaigns.set(id, { id, org, title, story, goal, lane: assignedLane });
  return jsonResponse(200, { campaign: id, lane: assignedLane });
}

export function showOrg({ params }) {
  const org = state.orgs.get(params.slug);
  if (!org) {
    return errorResponse(404, 'missing org');
  }
  const campaigns = Array.from(state.campaigns.values())
    .filter((c) => c.org === org.slug)
    .map((c) => ({ id: c.id, title: c.title, goal: c.goal, lane: c.lane }));
  return jsonResponse(200, { slug: org.slug, name: org.name, owner: org.owner, campaigns });
}

export function showCampaign({ params }) {
  const campaign = state.campaigns.get(params.campaign_id);
  if (!campaign) {
    return errorResponse(404, 'missing campaign');
  }
  return jsonResponse(200, {
    id: campaign.id,
    org: campaign.org,
    title: campaign.title,
    story: campaign.story,
    goal: campaign.goal,
    lane: campaign.lane,
  });
}
