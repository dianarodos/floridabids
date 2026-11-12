import { Composition } from "remotion";
import { Reel, ReelProps, reelDuration } from "./Reel";
import sample from "../props.sample.json";

export const Root = () => (
  <Composition
    id="Reel"
    component={Reel}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={300}
    defaultProps={sample as ReelProps}
    calculateMetadata={({ props }) => ({ durationInFrames: Math.ceil(reelDuration(props) * 30) })}
  />
);
