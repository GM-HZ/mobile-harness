// Only DSH's Office Kit consumer resolves this adapter. The engine remains the pinned upstream package.
export function createConverter(options) {
  return globalThis.__harmonyOffice.createConverter(options);
}
