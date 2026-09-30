import { useEffect, useState } from "react";
import { continueRender, delayRender, staticFile } from "remotion";
import * as THREE from "three";

const cache = new Map<string, Promise<THREE.Texture>>();

const load = (src: string) => {
  if (!cache.has(src)) {
    cache.set(
      src,
      new THREE.TextureLoader().loadAsync(staticFile(src)).then((t) => {
        t.colorSpace = THREE.SRGBColorSpace;
        t.anisotropy = 8;
        return t;
      }),
    );
  }
  return cache.get(src)!;
};

/** Loads textures before the frame is captured, so renders never contain a blank plane. */
export const useTextures = (srcs: string[]) => {
  const [textures, setTextures] = useState<THREE.Texture[] | null>(null);
  const key = srcs.join("|");
  const [handle] = useState(() => delayRender(`textures:${key.slice(0, 60)}`));
  useEffect(() => {
    Promise.all(srcs.map(load)).then((t) => {
      setTextures(t);
      continueRender(handle);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return textures;
};
