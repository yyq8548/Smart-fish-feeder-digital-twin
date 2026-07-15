import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("dashboard container packaging", () => {
  it("copies the visual assets into the nginx image", () => {
    const dockerfile = readFileSync("Dockerfile", "utf8");

    expect(dockerfile).toContain("COPY assets/ /usr/share/nginx/html/assets/");
  });
});
