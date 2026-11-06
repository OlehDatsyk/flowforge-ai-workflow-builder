import { expect, Page, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const shots = path.resolve(__dirname, "../../docs/screenshots");
const unique = Date.now();

async function shot(page: Page, name: string) {
  await page.waitForTimeout(350);
  await page.screenshot({ path: path.join(shots, `${name}.png`) });
}

async function register(page: Page, label: string) {
  await page.goto("/register");
  await page.getByLabel("Your name").fill(`${label} User`);
  await page.getByLabel("Email").fill(`${label}-${unique}@example.com`);
  await page.getByLabel(/^Password/).fill("correct-horse-battery");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

async function connect(page: Page, fromNode: string, toNode: string, fromPort?: string) {
  const source = page.getByTestId(`node-${fromNode}`).locator(fromPort ? `.react-flow__handle[data-handleid="${fromPort}"]` : ".react-flow__handle.source").first();
  const target = page.getByTestId(`node-${toNode}`).locator(".react-flow__handle.target").first();
  const a = (await source.boundingBox())!;
  const b = (await target.boundingBox())!;
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 12 });
  await page.mouse.up();
}

async function moveNode(page: Page, name: string, dx: number, dy: number) {
  const box = (await page.getByTestId(`node-${name}`).boundingBox())!;
  await page.mouse.move(box.x + 80, box.y + 18);
  await page.mouse.down();
  await page.mouse.move(box.x + 80 + dx, box.y + 18 + dy, { steps: 8 });
  await page.mouse.up();
}

const saved = (page: Page) => expect(page.getByTestId("save-state")).toHaveText("Saved", { timeout: 15_000 });

test("register, build a branching workflow by hand, save, reopen and run it", async ({ page }) => {
  await register(page, "builder");
  await expect(page.getByText("No data for this period").first()).toBeVisible();

  await page.getByRole("link", { name: "My Workflows" }).click();
  await expect(page.getByText("No workflows yet")).toBeVisible();
  await page.getByRole("button", { name: "New workflow" }).first().click();
  await expect(page.getByText("Start with a trigger")).toBeVisible();

  // Validation reports the empty workflow.
  await page.getByLabel("Workflow name").fill("Order Router");
  await page.getByLabel("Workflow name").blur();

  await page.getByTestId("lib-trigger.manual").click();
  await page.getByTestId("lib-logic.if").click();
  await page.getByTestId("lib-data.set").click();
  await page.getByTestId("lib-data.transform").click();
  await expect(page.getByTestId("node-Manual Trigger")).toBeVisible();

  // Spread nodes so handles do not overlap, then connect.
  await page.getByRole("button", { name: "Fit to screen" }).click();
  await page.waitForTimeout(300);
  await moveNode(page, "Transform Data", -280, 150);
  await saved(page);
  await page.getByRole("button", { name: "Fit to screen" }).click();
  await page.waitForTimeout(300);

  await connect(page, "Manual Trigger", "IF Condition");
  await connect(page, "IF Condition", "Set Variables", "true");
  await connect(page, "IF Condition", "Transform Data", "false");
  await expect(page.locator(".react-flow__edge")).toHaveCount(3);

  // Invalid connection: into a trigger is refused.
  await connect(page, "Set Variables", "IF Condition");
  await page.waitForTimeout(150);
  await expect(page.locator(".react-flow__edge")).toHaveCount(3, { timeout: 2000 });

  // Unconfigured nodes are reported.
  await saved(page);
  await expect(page.getByTestId("problem-count")).toContainText("problem");

  // Configure the trigger's data.
  await page.getByTestId("node-Manual Trigger").click();
  await page.locator("textarea").first().fill('{"amount": 750, "customer": "Ada"}');
  // IF condition
  await page.getByTestId("node-IF Condition").click();
  await page.getByLabel("Value", { exact: true }).fill("{{ input.amount }}");
  await page.getByLabel("Operator").selectOption("gt");
  await page.getByLabel("Compare to").fill("500");
  // Variables
  await page.getByTestId("node-Set Variables").click();
  await page.getByLabel("Name", { exact: true }).first().fill("tier");
  await page.getByLabel("Value", { exact: true }).fill('{{ input.customer | upper }} is high value');
  // Transform
  await page.getByTestId("node-Transform Data").click();
  await page.getByLabel("Operation", { exact: true }).selectOption("pick");
  await page.getByLabel("Field", { exact: true }).fill("customer");
  await saved(page);
  await expect(page.getByTestId("problem-count")).toContainText("Valid");
  await shot(page, "editor-configure");

  // Single-node test.
  await page.getByRole("tab", { name: "Test" }).click();
  await page.getByLabel("Test input").fill('{"customer":"Grace","amount":1}');
  await page.getByRole("button", { name: "Test this node" }).click();
  await expect(page.getByTestId("node-test-result")).toContainText("Grace");

  // Undo / redo are real.
  await page.getByRole("tab", { name: "Configure" }).click();
  await page.keyboard.press("Escape");
  await page.getByTestId("lib-logic.delay").click();
  await expect(page.getByTestId("node-Delay")).toBeVisible();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.getByTestId("node-Delay")).toHaveCount(0);
  await page.getByRole("button", { name: "Redo" }).click();
  await expect(page.getByTestId("node-Delay")).toBeVisible();
  // Duplicate, then delete via the panel.
  await page.getByTestId("node-Delay").click();
  await page.getByRole("button", { name: "Duplicate" }).first().click();
  await expect(page.getByTestId("node-Delay copy")).toBeVisible();
  await page.getByTestId("node-Delay copy").click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByTestId("node-Delay copy")).toHaveCount(0);
  await page.getByTestId("node-Delay").click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page.getByTestId("node-Delay")).toHaveCount(0);

  // Zoom controls.
  const before = await page.getByTestId("zoom-level").textContent();
  await page.getByRole("button", { name: "Zoom out" }).click();
  await expect(page.getByTestId("zoom-level")).not.toHaveText(before!);
  await saved(page);

  // Save and restore.
  await page.reload();
  await expect(page.getByTestId("node-Set Variables")).toBeVisible();
  await expect(page.locator(".react-flow__edge")).toHaveCount(3);
  await expect(page.getByLabel("Workflow name")).toHaveValue("Order Router");

  // Real backend run, through the true branch; the false branch is skipped.
  await page.getByRole("button", { name: "Run", exact: true }).click();
  const console = page.getByTestId("console-body");
  await expect(console.getByTestId("run-Set Variables")).toContainText(/ms|s/, { timeout: 15_000 });
  await expect(console.getByTestId("run-Transform Data")).toContainText("Skipped");
  await shot(page, "editor-run-result");

  await page.getByRole("link", { name: "Open inspector" }).click();
  await expect(page.getByText("Execution path")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Order Router" })).toBeVisible();
  await page.getByTestId("run-Set Variables").click();
  await expect(page.getByTestId("node-detail")).toContainText("ADA is high value");

  // History is persistent and lists it.
  await page.goto("/executions");
  await expect(page.getByRole("cell", { name: /Order Router/ })).toBeVisible();

  // Dashboard now shows real numbers, with no demo notice.
  await page.goto("/");
  await expect(page.getByLabel("Total executions", { exact: false }).or(page.getByText("Total executions"))).toBeVisible();
  await expect(page.getByText("generated demonstration records")).toHaveCount(0);

  // Failure path: an internal URL is blocked with a useful message.
  await page.goto("/workflows");
  await page.getByRole("heading", { name: "Order Router" }).click();
  await page.getByTestId("lib-integration.http").click();
  await page.getByLabel(/^URL/).fill("http://169.254.169.254/latest/meta-data/");
  await page.getByRole("button", { name: "Fit to screen" }).click();
  await page.waitForTimeout(300);
  await connect(page, "Set Variables", "HTTP Request");
  await saved(page);
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await expect(page.getByTestId("console-body")).toContainText("blocked", { timeout: 15_000 });
  await shot(page, "editor-failed-node");
});

test("templates, credentials, AI proposal review and settings", async ({ page }) => {
  await register(page, "explorer");

  await page.goto("/templates");
  await expect(page.getByTestId("template-card")).toHaveCount(8);
  await expect(page.getByText("Needs configuration").first()).toBeVisible();
  await page.getByRole("article").filter({ hasText: "AI Text Classification" }).getByRole("button", { name: "Use template" }).click();
  await expect(page.getByLabel("Workflow name")).toHaveValue("AI Text Classification");
  await page.getByRole("button", { name: "Test", exact: true }).click();
  await expect(page.getByTestId("console-body").getByTestId("run-Count by Label")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("console-body").getByText("Simulated").first()).toBeVisible();

  // Credentials: secret is masked after saving and never shown again.
  await page.goto("/credentials");
  await page.getByRole("button", { name: "Add credential" }).first().click();
  await page.getByLabel("Name").fill("Billing API");
  await page.getByLabel(/^Token/).fill("tok-supersecret-12345");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  const row = page.getByTestId("credential-row");
  await expect(row).toContainText("Billing API");
  await expect(row).toContainText("•");
  await expect(page.locator("body")).not.toContainText("tok-supersecret-12345");

  // AI builder: labelled demo mode, reviewed before saving.
  await page.goto("/ai");
  await expect(page.getByText("Demonstration mode.")).toBeVisible();
  await page.getByRole("button", { name: /When a new email arrives/ }).click();
  const proposal = page.getByTestId("proposal");
  await expect(proposal.getByText("Not supported as requested")).toBeVisible();
  await expect(proposal.getByText(/inbound email trigger/)).toBeVisible();
  await expect(proposal.getByText("Demo planner · no AI model")).toBeVisible();
  await shot(page, "ai-builder");
  await proposal.getByRole("button", { name: "Save and open in editor" }).click();
  await expect(page.getByTestId("node-Extract Fields")).toBeVisible();
  await expect(page.getByRole("button", { name: "Publish" })).toBeVisible(); // Inactive, not auto-published.

  // AI change proposal is applied only after review, and undo works.
  await page.getByRole("button", { name: "AI", exact: true }).click();
  await page.getByRole("button", { name: /error-handling branch/ }).click();
  await expect(page.getByTestId("ai-proposal")).toContainText("Log Failure");
  await expect(page.getByTestId("node-Log Failure")).toHaveCount(0);
  await page.getByRole("button", { name: "Apply to canvas" }).click();
  await expect(page.getByTestId("node-Log Failure")).toBeVisible();
  await shot(page, "editor-ai-assistant");
  await page.getByRole("button", { name: "Explain workflow" }).click();
  await expect(page.getByTestId("ai-explanation")).toContainText("Extract Fields");

  // Unsupported request is explained, not faked.
  await page.goto("/ai");
  await page.getByLabel("What should this workflow do?").fill("Post a message to Slack whenever Salesforce changes");
  await page.getByRole("button", { name: "Generate proposal" }).click();
  await expect(page.getByText("can't be built with the available nodes")).toBeVisible();
  await expect(page.getByText(/Slack has no built-in integration/)).toBeVisible();

  // Integrations and data store.
  await page.goto("/integrations");
  await expect(page.getByTestId("integration-http")).toContainText("Built in");
  await expect(page.getByTestId("integration-anthropic")).toContainText("Not configured");
  await page.getByTestId("integration-smtp").getByRole("button", { name: "Connect" }).click();
  await expect(page.getByRole("dialog")).toContainText("Connect Email (SMTP)");
  await page.getByRole("button", { name: "Cancel" }).click();

  // Settings pages and logout.
  await page.goto("/settings?tab=workspace");
  await expect(page.getByTestId("member-row")).toHaveCount(1);
  await page.goto("/settings?tab=audit");
  await expect(page.getByText("credential.create")).toBeVisible();
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.goto("/workflows");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible(); // Protected route.
});

test("demo workspace tour with labelled data, and screenshots", async ({ page }) => {
  await page.goto("/login");
  await shot(page, "login");
  await page.getByRole("button", { name: "Explore the demo workspace" }).click();
  await expect(page.getByText("generated demonstration records")).toBeVisible();
  await page.getByRole("button", { name: "Last 30 days" }).click();
  await page.waitForTimeout(600);
  await shot(page, "dashboard");

  await page.getByRole("link", { name: "My Workflows" }).click();
  await expect(page.getByTestId("workflow-card").first()).toBeVisible();
  await shot(page, "workflows");

  await page.goto("/templates");
  await expect(page.getByTestId("template-card").first()).toBeVisible();
  await page.waitForTimeout(500);
  await shot(page, "templates");

  await page.goto("/analytics");
  await expect(page.getByText("Execution volume")).toBeVisible();
  await page.waitForTimeout(500);
  await shot(page, "analytics");

  // Toggling demo records off changes the numbers honestly.
  await page.getByLabel("Include demonstration records").uncheck();
  await expect(page.getByText("generated demonstration records")).toHaveCount(0);
  await page.getByLabel("Include demonstration records").check();

  await page.goto("/integrations");
  await expect(page.getByTestId("integration-http")).toBeVisible();
  await shot(page, "integrations");

  // Open a failed demo record: labelled, canvas shows the failure.
  await page.goto("/executions?status=failed");
  await page.getByRole("row").nth(1).click();
  await expect(page.getByText("generated demonstration record")).toBeVisible();
  await expect(page.getByTestId("execution-error")).toBeVisible();
  await page.waitForTimeout(600);
  await shot(page, "execution-inspector");

  // Compare two executions.
  await page.goto("/executions");
  await page.getByRole("checkbox").nth(0).check();
  await page.getByRole("checkbox").nth(1).check();
  await page.getByRole("button", { name: /Compare/ }).click();
  await expect(page.getByRole("heading", { name: "Compare executions" })).toBeVisible();
  await expect(page.getByTestId("compare-row").first()).toBeVisible();

  // A demo workflow runs for real.
  await page.goto("/workflows");
  await page.getByRole("heading", { name: "Daily Order Digest" }).click();
  await expect(page.getByTestId("node-Paid Orders")).toBeVisible();
  await page.waitForTimeout(500);
  await shot(page, "editor");
  await page.getByRole("button", { name: "Run", exact: true }).click();
  await page.getByRole("button", { name: "Run for real" }).click();
  await expect(page.getByTestId("console-body").getByTestId("run-Save Digest")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId("console-body").getByTestId("run-Quiet Day")).toContainText("Skipped");

  // Mobile: inspect history and workflows.
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/executions");
  await expect(page.getByRole("heading", { name: "Execution History" })).toBeVisible();
  await shot(page, "mobile-history");
  await page.getByRole("button", { name: "Open menu" }).click();
  await page.getByRole("link", { name: "My Workflows" }).click();
  await page.getByRole("heading", { name: "Daily Order Digest" }).click();
  await expect(page.getByText("The editor needs a larger screen")).toBeVisible();
  await shot(page, "mobile-workflow");
});
