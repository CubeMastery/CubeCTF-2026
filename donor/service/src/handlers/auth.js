import { state, newId } from '../state.js';
import { parseForm, clean, escape, formDefault } from '../util.js';
import { jsonResponse, errorResponse } from '../response.js';

export function registerUser({ body }) {
  const form = parseForm(body);
  const username = clean(formDefault(form, 'username', ''));
  const password = formDefault(form, 'password', '');
  const display = escape(formDefault(form, 'display', username));
  if (username.length < 3 || password.length < 4) {
    return errorResponse(400, 'invalid registration');
  }
  if (state.users.has(username)) {
    return errorResponse(409, 'username exists');
  }
  state.users.set(username, { password, display });
  return jsonResponse(200, { username });
}

export function registerOrg({ body }) {
  const form = parseForm(body);
  const username = clean(formDefault(form, 'username', ''));
  const password = formDefault(form, 'password', '');
  const slug = clean(formDefault(form, 'org_slug', ''));
  const name = escape(formDefault(form, 'org_name', slug));
  const vault = escape(formDefault(form, 'vault', ''));
  if (username.length < 3 || password.length < 4 || slug.length < 3) {
    return errorResponse(400, 'invalid organization');
  }
  if (state.users.has(username) || state.orgs.has(slug)) {
    return errorResponse(409, 'name exists');
  }
  state.users.set(username, { password, display: name });
  state.orgs.set(slug, { slug, name, owner: username, admins: [username], vault });
  return jsonResponse(200, { org: slug });
}

export function login({ body }) {
  const form = parseForm(body);
  const username = formDefault(form, 'username', '');
  const password = formDefault(form, 'password', '');
  const user = state.users.get(username);
  if (!user || user.password !== password) {
    return errorResponse(403, 'login failed');
  }
  const sid = newId('s');
  state.sessions.set(sid, username);
  const response = jsonResponse(200, { username: escape(username), display: user.display });
  response.headers.push(['Set-Cookie', `sid=${sid}; Path=/; HttpOnly`]);
  return response;
}
