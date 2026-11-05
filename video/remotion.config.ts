import { Config } from "@remotion/cli/config";

// UI text must stay crisp: lossless frames, the encoder does the compression.
Config.setVideoImageFormat("png");
Config.setOverwriteOutput(true);
