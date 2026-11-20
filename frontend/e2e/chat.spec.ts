import { expect, test, Page } from "@playwright/test";
import { readFile } from "node:fs/promises";

const metadata = { resolution_source: "LIVE_INFERENCE", model: "gemini/gemini-3.1-flash-lite", latency_ms: 812, input_tokens: 24, output_tokens: 12, key_id: "key_1", fallback_attempts: 0 };
const reply = "## Hello, Dishant\n\nHere is a **clear plan**.\n\n```python\nprint('hello')\n```";

async function mockHealth(page: Page) {
  await page.route("**/health", (route) => route.fulfill({ json: { status: "ok", keys_configured: 2, cache_enabled: true } }));
}
test.beforeEach(async ({ page }) => { await mockHealth(page); });

test("welcome, visible composer, prompt cards and persistent theme", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Good ideas start/ })).toBeVisible();
  await expect(page.getByTestId("chat-input")).toBeInViewport();
  await expect(page.getByTestId("send-button")).toBeDisabled();
  await page.screenshot({ path: "test-results/modern-desktop.png", fullPage: true });
  await page.getByRole("button", { name: /Build something/ }).click();
  await expect(page.getByTestId("chat-input")).toBeFocused();
  await expect(page.getByTestId("chat-input")).toHaveValue(/Help me plan/);
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({ path: "test-results/modern-dark.png", fullPage: true });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("chat renders markdown and required metadata, copies and exports", async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(navigator, "clipboard", { value: { writeText: async () => undefined } }); });
  await page.route("**/chat", (route) => route.fulfill({ json: { session_id: route.request().postDataJSON().session_id, reply, metadata } }));
  await page.goto("/");
  await page.getByTestId("chat-input").fill("My name is Dishant");
  await page.getByTestId("chat-input").press("Enter");
  await expect(page.getByTestId("chat-input")).toHaveValue("");
  const response = page.getByTestId("assistant-message");
  await expect(response.getByRole("heading", { name: "Hello, Dishant" })).toBeVisible();
  await expect(response.locator("pre code")).toContainText("print('hello')");
  await expect(response.getByTestId("meta-source")).toHaveText("LIVE_INFERENCE");
  await expect(response.getByTestId("meta-model")).toBeVisible();
  await expect(response.getByTestId("meta-input-tokens")).toHaveText("24");
  await expect(response.getByTestId("meta-output-tokens")).toHaveText("12");
  await expect(response.getByTestId("meta-latency")).toHaveText("812 ms");
  await response.getByRole("button", { name: "Copy reply" }).click();
  await expect(response.getByRole("button", { name: "Reply copied" })).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export conversation" }).click();
  const file = await download;
  expect(await readFile((await file.path())!, "utf8")).toContain("My name is Dishant");
  await page.screenshot({ path: "test-results/modern-conversation.png", fullPage: true });
});

test("new conversation and saved history use the correct session", async ({ page }) => {
  let firstSession = "";
  await page.route("**/chat", (route) => {
    firstSession = route.request().postDataJSON().session_id;
    return route.fulfill({ json: { session_id: firstSession, reply: "Your name is Dishant.", metadata } });
  });
  await page.route("**/sessions/*/messages", (route) => {
    expect(route.request().url()).toContain(firstSession);
    return route.fulfill({ json: { session_id: firstSession, messages: [{ role: "user", content: "Remember Dishant" }, { role: "assistant", content: "Your name is Dishant.", metadata }] } });
  });
  await page.goto("/");
  await page.getByTestId("chat-input").fill("Remember Dishant");
  await page.getByTestId("send-button").click();
  await expect(page.getByTestId("assistant-message")).toBeVisible();
  await page.getByRole("button", { name: "New conversation" }).click();
  await expect(page.getByRole("heading", { name: /Good ideas start/ })).toBeVisible();
  await page.getByRole("button", { name: "Remember Dishant", exact: true }).click();
  await expect(page.getByTestId("assistant-message")).toContainText("Your name is Dishant.");
  await page.reload();
  // A reload starts a new chat, while the sidebar retains an explicit history link.
  await expect(page.getByRole("heading", { name: /Good ideas start/ })).toBeVisible();
  await expect(page.getByRole("button", { name: "Remember Dishant", exact: true })).toBeVisible();
});

test("failover applies once and errors offer edit and retry", async ({ page }) => {
  const failures: (string | undefined)[] = [];
  await page.route("**/chat", (route) => {
    failures.push(route.request().headers()["x-simulate-failure"]);
    return failures.length === 1
      ? route.fulfill({ status: 503, json: { detail: "all providers unavailable" } })
      : route.fulfill({ json: { reply: "Recovered", metadata, session_id: route.request().postDataJSON().session_id } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Open conversation settings" }).click();
  await page.getByTestId("system-prompt-input").fill("Be concise.");
  await page.getByText("Developer tools", { exact: true }).click();
  await page.locator("#failure-mode").selectOption("*=429");
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(page.getByText("Failure simulation is on for your next message.")).toBeVisible();
  await page.getByTestId("chat-input").fill("Hello");
  await page.getByTestId("send-button").click();
  await expect(page.getByText("all providers unavailable", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit & retry" }).click();
  await expect(page.getByTestId("chat-input")).toHaveValue("Hello");
  await page.getByTestId("send-button").click();
  await expect(page.getByTestId("assistant-message")).toContainText("Recovered");
  expect(failures).toEqual(["*=429", undefined]);
});

test("mobile layout keeps input visible and navigation accessible", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByTestId("chat-input")).toBeInViewport();
  await expect(page.getByRole("button", { name: "New conversation" })).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: "test-results/modern-mobile.png", fullPage: true });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(page.getByRole("button", { name: "New conversation" })).toBeInViewport();
  await page.getByRole("button", { name: "New conversation" }).click();
  await expect(page.getByTestId("chat-input")).toBeInViewport();
});

test("message limit and Shift Enter prevent accidental sends", async ({ page }) => {
  let sends = 0;
  await page.route("**/chat", (route) => { sends += 1; return route.fulfill({ json: { reply: "Done", metadata, session_id: "test" } }); });
  await page.goto("/");
  await page.getByTestId("chat-input").fill("x".repeat(4001));
  await expect(page.getByTestId("send-button")).toBeDisabled();
  await page.getByTestId("chat-input").fill("First line");
  await page.getByTestId("chat-input").press("Shift+Enter");
  await expect(page.getByTestId("chat-input")).toHaveValue("First line\n");
  expect(sends).toBe(0);
  await page.getByTestId("chat-input").press("Enter");
  await expect(page.getByTestId("assistant-message")).toBeVisible();
  expect(sends).toBe(1);
});

test("assistant instructions can be set and explicitly reset", async ({ page }) => {
  const prompts: (string | undefined)[] = [];
  await page.route("**/chat", (route) => {
    prompts.push(route.request().postDataJSON().system_prompt);
    return route.fulfill({ json: { reply: "Done", metadata, session_id: "test" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Open conversation settings" }).click();
  await page.getByTestId("system-prompt-input").fill("Be concise.");
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await page.getByTestId("chat-input").fill("First question");
  await page.getByTestId("send-button").click();
  await expect(page.getByTestId("assistant-message")).toHaveCount(1);
  await page.getByRole("button", { name: "Open conversation settings" }).click();
  await page.getByRole("button", { name: "Use default instructions" }).click();
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await page.getByTestId("chat-input").fill("Second question");
  await page.getByTestId("send-button").click();
  await expect(page.getByTestId("assistant-message")).toHaveCount(2);
  expect(prompts).toEqual(["Be concise.", ""]);
});
