// Global reactive-ish state + event bus.
export const S = {
  app: {}, network: {}, scan: {}, devices: [], monitor: {}, license: { features: [] }, settings: {}, update: {},
  unread: 0, blocking: {}, remote: {}, speed_last: null, audit_last: null, bandwidth: {}, bw: [], ws: false,
};
const bus = new EventTarget();
export const on = (type, fn) => { const h = (e) => fn(e.detail); bus.addEventListener(type, h); return () => bus.removeEventListener(type, h); };
export const emit = (type, detail) => bus.dispatchEvent(new CustomEvent(type, { detail }));
export const can = (f) => (S.license?.features || []).includes(f);
export const device = (id) => S.devices.find((d) => d.id === id);
export function upsertDevice(d) {
  const i = S.devices.findIndex((x) => x.id === d.id);
  if (i >= 0) S.devices[i] = { ...S.devices[i], ...d }; else S.devices.push(d);
}
