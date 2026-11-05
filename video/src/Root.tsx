import { Composition } from "remotion";
import { DEMO_FRAMES, Demo, DemoShort, SHORT_FRAMES } from "./Demo";
import { FPS, H, W } from "./theme";

export function Root() {
  return (
    <>
      <Composition id="Demo" component={Demo} durationInFrames={DEMO_FRAMES} fps={FPS} width={W} height={H} />
      <Composition id="DemoShort" component={DemoShort} durationInFrames={SHORT_FRAMES} fps={FPS} width={W} height={H} />
    </>
  );
}

