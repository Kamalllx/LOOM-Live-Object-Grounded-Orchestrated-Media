import { Composition, Folder } from "remotion";
import { LoomFilm } from "./compositions/LoomFilm";
import { SCENES } from "./scenes";
import { FILM_DURATION, FPS, HEIGHT, SCENE_ORDER, WIDTH, sceneTiming } from "./theme/timing";
import "./theme/type";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="LoomFilm" component={LoomFilm} durationInFrames={FILM_DURATION} fps={FPS} width={WIDTH} height={HEIGHT} />
    <Folder name="Scenes">
      {SCENE_ORDER.map((key) => {
        const s = SCENES[key];
        if (!s) return null;
        return (
          <Composition key={key} id={s.id} component={s.component} durationInFrames={sceneTiming(key).duration} fps={FPS} width={WIDTH} height={HEIGHT} />
        );
      })}
    </Folder>
  </>
);
