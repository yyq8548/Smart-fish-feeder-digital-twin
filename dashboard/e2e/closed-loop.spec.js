import { expect, test } from "@playwright/test";

test("dashboard FEED_NOW completes through the Wokwi ESP32", async ({ page }) => {
  const username = process.env.E2E_ADMIN_USERNAME;
  const password = process.env.E2E_ADMIN_PASSWORD;
  const deviceUid = process.env.E2E_DEVICE_UID;
  expect(username, "E2E_ADMIN_USERNAME is required").toBeTruthy();
  expect(password, "E2E_ADMIN_PASSWORD is required").toBeTruthy();
  expect(deviceUid, "E2E_DEVICE_UID is required").toBeTruthy();

  page.on("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.locator("#deviceSelect")).toHaveValue(deviceUid);
  const feedButton = page.getByRole("button", { name: "Feed now" });
  await expect(feedButton).toBeEnabled();
  await expect(page.locator("#controlState")).toContainText("Device is online");

  await page.getByLabel("Feed duration (ms)").fill("500");
  const createResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes(`/api/devices/${encodeURIComponent(deviceUid)}/commands`)
  );
  await feedButton.click();
  const response = await createResponse;
  expect(response.ok()).toBe(true);
  const acceptedCommand = await response.json();
  expect(acceptedCommand.command_type).toBe("FEED_NOW");
  expect(acceptedCommand.status).toBe("PENDING");

  const command = page.locator("#commandHistory li", { hasText: "FEED_NOW" }).first();
  await expect(command).toBeVisible();
  await expect(command).toContainText("COMPLETED");
  await expect(command).toContainText("feeding_and_cleaning_completed");
});
