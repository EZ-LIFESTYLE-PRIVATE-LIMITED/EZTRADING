// Tiny shared state + pub/sub so views stay decoupled.

const listeners = new Map();

export const state = {
  config: {},
  me: null,
  status: null,
  styles: [],
  style: null,
  settings: null,
  plan: null,
};

export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, []);
  listeners.get(event).push(fn);
}

export function emit(event, payload) {
  (listeners.get(event) || []).forEach((fn) => fn(payload));
}
