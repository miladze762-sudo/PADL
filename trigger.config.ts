import { defineConfig } from "@trigger.dev/sdk";
import { pythonExtension } from "@trigger.dev/python/extension";

export default defineConfig({
  project: "proj_idvrbofrajznnafltimb",
  runtime: "node",
  logLevel: "log",
  maxDuration: 3600,
  retries: {
    enabledInDev: true,
    default: {
      maxAttempts: 3,
      minTimeoutInMs: 1000,
      maxTimeoutInMs: 10000,
      factor: 2,
      randomize: true,
    },
  },
  dirs: ["./src/trigger"],
  build: {
    extensions: [
      pythonExtension({
        scripts: ["./padlbot/**/*.py", "./src/trigger/**/*.py"],
        requirementsFile: "./requirements.txt",
      }),
    ],
  },
});
