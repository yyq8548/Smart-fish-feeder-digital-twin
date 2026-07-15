import { expect, test } from "@playwright/test";

const viewports = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 }
];

for (const viewport of viewports) {
  test(`${viewport.name} dashboard layout stays contained`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Feed Smarter. Worry Less." })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Dashboard sections" })).toBeVisible();

    const layout = await page.evaluate(() => {
      const rectangle = (selector) => {
        const element = document.querySelector(selector);
        if (!element) return null;
        const bounds = element.getBoundingClientRect();
        return {
          left: bounds.left,
          right: bounds.right,
          top: bounds.top,
          bottom: bounds.bottom,
          width: bounds.width,
          height: bounds.height
        };
      };
      return {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        hero: rectangle(".aquarium-hero"),
        actions: rectangle(".hero-primary-actions"),
        butler: rectangle(".scene-butler"),
        navigation: rectangle(".quick-nav"),
        brokenImages: [...document.images]
          .filter((image) => !image.complete || image.naturalWidth === 0)
          .map((image) => image.currentSrc || image.src)
      };
    });

    expect(layout.scrollWidth).toBeLessThanOrEqual(layout.clientWidth);
    expect(layout.brokenImages).toEqual([]);
    for (const region of [layout.hero, layout.actions, layout.butler, layout.navigation]) {
      expect(region).not.toBeNull();
      expect(region.left).toBeGreaterThanOrEqual(0);
      expect(region.right).toBeLessThanOrEqual(layout.clientWidth);
      expect(region.width).toBeGreaterThan(0);
      expect(region.height).toBeGreaterThan(0);
    }
  });
}

test("reduced motion keeps critical content visible and disables parallax", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");

  const presentation = await page.evaluate(() => {
    const heroHeading = document.querySelector(".aquarium-copy .mask-line-inner");
    const aquariumVideo = document.querySelector(".aquarium-backdrop");
    const revealSection = document.querySelector("[data-reveal]");
    return {
      motionEnabled: document.body.classList.contains("motion-enabled"),
      headingTransform: getComputedStyle(heroHeading).transform,
      videoTransform: getComputedStyle(aquariumVideo).transform,
      revealOpacity: getComputedStyle(revealSection).opacity
    };
  });

  expect(presentation.motionEnabled).toBe(false);
  expect(presentation.headingTransform).toBe("none");
  expect(presentation.videoTransform).toBe("none");
  expect(presentation.revealOpacity).toBe("1");
});

test("customer sign-up and recovery remain usable on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#dashboard");
  await page.getByRole("tab", { name: "Create account" }).click();
  const registrationForm = page.locator("#registrationForm");
  await expect(registrationForm.getByRole("button", { name: "Create account", exact: true })).toBeVisible();
  await expect(registrationForm.getByLabel("Email", { exact: true })).toBeVisible();
  await expect(registrationForm.getByLabel("Confirm password")).toBeVisible();

  const signUpLayout = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
    formWidth: document.getElementById("registrationForm").getBoundingClientRect().width
  }));
  expect(signUpLayout.scrollWidth).toBeLessThanOrEqual(signUpLayout.clientWidth);
  expect(signUpLayout.formWidth).toBeLessThanOrEqual(signUpLayout.clientWidth);

  await page.getByRole("tab", { name: "Sign in" }).click();
  await page.getByRole("button", { name: "Forgot password?" }).click();
  await expect(page.getByRole("button", { name: "Send reset link" })).toBeVisible();
});
