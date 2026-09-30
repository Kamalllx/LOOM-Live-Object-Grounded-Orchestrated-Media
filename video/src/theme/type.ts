import { loadFont as loadSerif } from "@remotion/google-fonts/InstrumentSerif";
import { loadFont as loadSans } from "@remotion/google-fonts/InterTight";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";

const serif = loadSerif("normal", { weights: ["400"], subsets: ["latin"] });
const serifItalic = loadSerif("italic", { weights: ["400"], subsets: ["latin"] });
const sans = loadSans("normal", { weights: ["400", "500", "600"], subsets: ["latin"] });
const mono = loadMono("normal", { weights: ["400", "500"], subsets: ["latin"] });

void serifItalic;

export const fonts = {
  serif: serif.fontFamily,
  sans: sans.fontFamily,
  mono: mono.fontFamily,
};

export const typeScale = {
  statement: 92,
  statementSm: 64,
  title: 44,
  label: 24,
  data: 21,
  micro: 17,
};
