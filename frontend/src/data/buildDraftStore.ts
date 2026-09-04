import { hydrateLocalBuild, type BuildState } from "../model/build";
import type { CatalogueIndex } from "../model/catalogue";

const LOCAL_BUILD_KEY = "afe2-build-editor:local-build:v1";

export interface BuildDraftStore {
  load(index: CatalogueIndex): BuildState | null;
  save(build: BuildState): void;
}

export const browserBuildDraftStore: BuildDraftStore = {
  load(index) {
    try {
      return hydrateLocalBuild(index, localStorage.getItem(LOCAL_BUILD_KEY));
    } catch {
      return null;
    }
  },
  save(build) {
    try {
      localStorage.setItem(LOCAL_BUILD_KEY, JSON.stringify(build));
    } catch {
      // The editor remains usable when storage is blocked or full.
    }
  },
};
