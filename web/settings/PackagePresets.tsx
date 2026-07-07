// Saved box sizes so merchants don't retype dimensions for every order.
export type Preset = { name: string; dimsIn: [number, number, number]; weightOz: number };

export const DEFAULT_PRESETS: Preset[] = [
  { name: "Poly mailer", dimsIn: [10, 13, 1], weightOz: 2 },
  { name: "Small box", dimsIn: [8, 6, 4], weightOz: 6 },
  { name: "Medium box", dimsIn: [12, 10, 6], weightOz: 10 },
];
