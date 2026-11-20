const paths = {
  layers: "m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5",
  plus: "M12 5v14M5 12h14", arrow: "M5 12h14m-5-5 5 5-5 5", arrowUp: "M12 19V5m-6 6 6-6 6 6",
  chat: "M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-1 1V11.5A8.5 8.5 0 0 1 11.5 3h1a8.5 8.5 0 0 1 8.5 8.5Z",
  sparkles: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3ZM20 2v4m-2-2h4",
  code: "m8 7-5 5 5 5m8-10 5 5-5 5m-3-13-2 16", edit: "m16 3 5 5-12 12-6 1 1-6L16 3Zm-2 2 5 5",
  shield: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Zm-4 9 3 3 5-6",
  settings: "M9 3h6l1 4 4 1v8l-4 1-1 4H9l-1-4-4-1V8l4-1 1-4ZM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z",
  sliders: "M4 7h9m4 0h3M4 17h3m4 0h9M13 4v6M7 14v6", chevron: "m9 5 7 7-7 7",
  search: "M10.5 3a7.5 7.5 0 1 0 0 15 7.5 7.5 0 0 0 0-15ZM16 16l5 5", pulse: "M2 12h5l3-8 4 16 3-8h5",
  bolt: "m13 2-9 12h7l-1 8 10-13h-7l1-7Z", clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm0 4v5l3 2",
  moon: "M20.7 13A9 9 0 0 1 11 3.3 9 9 0 1 0 20.7 13Z",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5",
  download: "M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5", menu: "M4 6h16M4 12h16M4 18h16", close: "m6 6 12 12M6 18 18 6",
  user: "M12 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM4 21v-2a8 6 0 0 1 16 0v2", alert: "m12 3 10 18H2L12 3Zm0 5v5m0 3v1",
  copy: "M9 8h12v13H9V8ZM5 16H3V3h12v2", check: "m5 12 4 4L19 6", retry: "M3 11a9 9 0 1 1 2 7M3 4v7h7",
};
export function Icon({ name, size = 20 }: { name: keyof typeof paths; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}
