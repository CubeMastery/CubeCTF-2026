export const state = {
  users: new Map(),
  orgs: new Map(),
  campaigns: new Map(),
  donations: new Map(),
  sessions: new Map(),
  handoffs: new Map(),
  sequence: 0n,
};

export function newId(prefix) {
  state.sequence += 1n;
  return prefix + state.sequence.toString(16).padStart(8, '0');
}
