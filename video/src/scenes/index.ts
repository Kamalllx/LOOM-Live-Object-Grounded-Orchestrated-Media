import { SceneKey } from "../theme/timing";
import { S01Problem } from "./S01Problem";
import { S02Ceiling } from "./S02Ceiling";
import { S03Shift } from "./S03Shift";
import { S04Perception } from "./S04Perception";
import { S05Mesh } from "./S05Mesh";
import { S06Verify } from "./S06Verify";
import { S07Viewer } from "./S07Viewer";
import { S08Result } from "./S08Result";
import { S09Finale } from "./S09Finale";

export const SCENES: Partial<Record<SceneKey, { id: string; component: React.FC }>> = {
  s01: { id: "S01-Problem", component: S01Problem },
  s02: { id: "S02-Ceiling", component: S02Ceiling },
  s03: { id: "S03-Shift", component: S03Shift },
  s04: { id: "S04-Perception", component: S04Perception },
  s05: { id: "S05-Mesh", component: S05Mesh },
  s06: { id: "S06-Verify", component: S06Verify },
  s07: { id: "S07-Viewer", component: S07Viewer },
  s08: { id: "S08-Result", component: S08Result },
  s09: { id: "S09-Finale", component: S09Finale },
};
