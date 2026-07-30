const path = require("node:path");
const runtimeNodeModules = path.resolve(path.dirname(process.execPath), "..", "node_modules");
const { chromium } = require(path.join(runtimeNodeModules, "playwright"));

const screenshotPath = path.resolve(__dirname, "..", "temp", "link-import-dialog-smoke.png");
let jobStatusRequests = 0;

async function jsonResponse(route, payload, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
}

async function handleApi(route) {
  const request = route.request();
  const url = new URL(request.url());
  if (url.pathname === "/api/status") {
    await jsonResponse(route, {
      api_version: 3,
      id: null,
      hash: null,
      status: "idle",
      progress: 0,
      message: "等待导入视频",
      video_name: null,
      duration: 0,
      error: null,
      engine: null,
      fallback_reason: null,
      segment_count: 0,
    });
  } else if (url.pathname === "/api/history") {
    await jsonResponse(route, { items: [] });
  } else if (url.pathname === "/api/link-import" && request.method() === "POST") {
    await jsonResponse(route, { task_id: "smoke-task", platform: "douyin" }, 202);
  } else if (url.pathname === "/api/link-import/smoke-task" && request.method() === "GET") {
    jobStatusRequests += 1;
    if (jobStatusRequests < 2) {
      await jsonResponse(route, {
        task_id: "smoke-task",
        status: "link_downloading",
        progress: 38,
        message: "正在下载视频",
        platform: "douyin",
        error: null,
        result: null,
      });
    } else {
      await jsonResponse(route, {
        task_id: "smoke-task",
        status: "done",
        progress: 100,
        message: "视频已导入",
        platform: "douyin",
        error: null,
        result: {
          exists: false,
          hash: "smoke-hash",
          item: { hash: "smoke-hash", video_name: "示例视频.mp4", status: "untranscribed" },
        },
      });
    }
  } else if (url.pathname === "/api/video") {
    await route.fulfill({ status: 204, body: "" });
  } else {
    await jsonResponse(route, { detail: "Unexpected smoke-test request" }, 500);
  }
}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(String(error)));
  await page.route("**/api/**", handleApi);
  await page.goto("http://127.0.0.1:8877");
  await page.waitForLoadState("networkidle");

  await page.getByRole("button", { name: "导入本地视频" }).waitFor({ state: "visible" });
  await page.getByRole("button", { name: "链接导入" }).click();
  const dialog = page.getByRole("dialog", { name: "链接导入视频" });
  await dialog.waitFor({ state: "visible" });
  await page.getByLabel("粘贴视频链接或完整分享文本").fill(
    "复制这段内容打开抖音 https://v.douyin.com/example/",
  );
  await page.screenshot({ path: screenshotPath, fullPage: true });
  await page.getByRole("button", { name: "解析并导入" }).click();
  await page.getByText("正在下载视频", { exact: true }).waitFor({ state: "visible" });
  await dialog.waitFor({ state: "hidden", timeout: 5000 });
  await page.getByText("未转写", { exact: true }).waitFor({ state: "visible" });
  if (pageErrors.length) throw new Error(`Page errors: ${pageErrors.join(" | ")}`);

  await browser.close();
  console.log(`UI smoke test passed; screenshot: ${screenshotPath}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
