import { Config } from "@remotion/cli/config";
// Use the Chromium already installed on the machine (cloud workspace / GitHub runner) when present.
if (process.env.REMOTION_BROWSER) Config.setBrowserExecutable(process.env.REMOTION_BROWSER);
Config.setVideoImageFormat("jpeg");
Config.setConcurrency(1);
Config.setOffthreadVideoCacheSizeInBytes(400 * 1024 * 1024);   // keep memory low on small machines
