import { createReadStream, existsSync, readFileSync, realpathSync, statSync } from "node:fs";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import type { Connect, Plugin } from "vite";
import { defineConfig } from "vitest/config";

const frontendDirectory = fileURLToPath(new URL(".", import.meta.url));
const catalogueDirectory = resolve(frontendDirectory, "../.local/catalogue");
const builtCatalogueDirectory = resolve(frontendDirectory, "dist/catalogue");
const plannerPath = resolve(catalogueDirectory, "planner-catalogue.json");

const MIME_TYPES: Record<string, string> = {
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
};

function collectAssetPaths(value: unknown, paths = new Set<string>()): Set<string> {
  if (Array.isArray(value)) {
    value.forEach((entry) => collectAssetPaths(entry, paths));
    return paths;
  }

  if (!value || typeof value !== "object") return paths;

  for (const [key, entry] of Object.entries(value)) {
    if (
      key === "path" &&
      typeof entry === "string" &&
      (entry.startsWith("icons/") || entry.startsWith("grid-assets/"))
    ) {
      paths.add(entry);
    } else {
      collectAssetPaths(entry, paths);
    }
  }
  return paths;
}

function isInsideDirectory(directory: string, filePath: string): boolean {
  return filePath === directory || filePath.startsWith(`${directory}${sep}`);
}

function mountCatalogueMiddleware(middlewares: Connect.Server, directory: string): void {
  middlewares.use("/catalogue", (request, response) => {
    if (request.method !== "GET" && request.method !== "HEAD") {
      response.statusCode = 405;
      response.setHeader("Allow", "GET, HEAD");
      response.end("Method not allowed");
      return;
    }
    const rawPath = (request.url ?? "/").split("?", 1)[0];
    let pathname: string;
    try {
      pathname = decodeURIComponent(rawPath);
    } catch {
      response.statusCode = 400;
      response.end("Invalid catalogue path");
      return;
    }

    const filePath = resolve(directory, `.${pathname}`);
    if (!isInsideDirectory(directory, filePath)) {
      response.statusCode = 403;
      response.end("Catalogue path is outside the publication root");
      return;
    }
    if (!existsSync(filePath)) {
      response.statusCode = 404;
      response.end("Catalogue asset not found");
      return;
    }

    let realFilePath: string;
    try {
      const realDirectory = realpathSync(directory);
      realFilePath = realpathSync(filePath);
      if (!isInsideDirectory(realDirectory, realFilePath)) {
        response.statusCode = 403;
        response.end("Catalogue path is outside the publication root");
        return;
      }
      if (!statSync(realFilePath).isFile()) {
        response.statusCode = 404;
        response.end("Catalogue asset not found");
        return;
      }
    } catch {
      response.statusCode = 404;
      response.end("Catalogue asset not found");
      return;
    }

    response.setHeader("Content-Type", MIME_TYPES[extname(realFilePath)] ?? "application/octet-stream");
    response.setHeader("Cache-Control", "no-cache");
    if (request.method === "HEAD") {
      response.end();
      return;
    }
    const stream = createReadStream(realFilePath);
    stream.once("error", (error) => {
      if (response.headersSent) response.destroy(error);
      else {
        response.statusCode = 404;
        response.setHeader("Content-Type", "text/plain; charset=utf-8");
        response.end("Catalogue asset no longer exists");
      }
    });
    stream.pipe(response);
  });
}

function localCataloguePlugin(): Plugin {
  return {
    name: "afe2-local-catalogue",
    configureServer(server) {
      mountCatalogueMiddleware(server.middlewares, catalogueDirectory);
    },
    configurePreviewServer(server) {
      mountCatalogueMiddleware(server.middlewares, builtCatalogueDirectory);
    },
    generateBundle() {
      if (!existsSync(plannerPath)) {
        throw new Error(
          `Missing ${plannerPath}. Run the catalogue extractor before building the frontend.`,
        );
      }

      const realPlannerPath = realpathSync(plannerPath);
      const realCatalogueDirectory = realpathSync(catalogueDirectory);
      if (!isInsideDirectory(realCatalogueDirectory, realPlannerPath) || !statSync(realPlannerPath).isFile()) {
        throw new Error(`Planner path is outside the local catalogue: ${plannerPath}`);
      }
      const plannerSource = readFileSync(realPlannerPath);
      const planner = JSON.parse(plannerSource.toString("utf8")) as unknown;
      this.emitFile({
        type: "asset",
        fileName: "catalogue/planner-catalogue.json",
        source: plannerSource,
      });

      for (const relativePath of [...collectAssetPaths(planner)].sort()) {
        const assetPath = resolve(catalogueDirectory, relativePath);
        if (!isInsideDirectory(catalogueDirectory, assetPath) || !existsSync(assetPath)) {
          throw new Error(`Planner references a missing catalogue asset: ${relativePath}`);
        }
        const realAssetPath = realpathSync(assetPath);
        if (!isInsideDirectory(realCatalogueDirectory, realAssetPath) || !statSync(realAssetPath).isFile()) {
          throw new Error(`Planner references an unsafe catalogue asset: ${relativePath}`);
        }
        this.emitFile({
          type: "asset",
          fileName: `catalogue/${relativePath}`,
          source: readFileSync(realAssetPath),
        });
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), localCataloguePlugin()],
  build: {
    target: "es2022",
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
