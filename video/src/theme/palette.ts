// Each accent carries exactly one meaning across the whole film.
export const palette = {
  ink: "#0B0C10",
  ink2: "#141728",
  line: "rgba(245,243,237,0.12)",
  paper: "#F5F3ED",
  muted: "#8A8C99",
  amber: "#FFB020", // perception / objects
  teal: "#2DD4C7", // agent mesh
  violet: "#A78BFA", // verification loop
  rose: "#FF6584", // redaction
} as const;

export type Accent = "amber" | "teal" | "violet" | "rose" | "paper";

export const alpha = (hex: string, a: number) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};
