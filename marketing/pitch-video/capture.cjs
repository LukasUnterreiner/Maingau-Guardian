#!/usr/bin/env node
// Clicks through the running Lighty web app and saves every step as a frame for the pitch video.
//
//   node capture.cjs [--app http://127.0.0.1:8501] [--out demo-frames]
//
// Needs the backend and the web app running with demo data (see README.md, "Recording the demo").
// Everything on these frames is the real app: real pages, real clicks, real scrolling, a real chat answer.
// Only the mouse pointer is added later by the video, because headless Chromium does not draw one.
//
// Output: <out>/NNNN.jpg (1600×900 CSS px at 2× = 3200×1800) and <out>/manifest.json with the clips
// (consecutive frames) and the on-screen boxes of everything the video points at or zooms to.
"use strict";
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const DIR = __dirname;
const VIEW = { width: 1600, height: 900 };
const CUSTOMER = "MG-100448";                       // joined Oct 2025, price guarantee ends, open complaint
const QUESTION = "How can I retain this customer?";

function args(argv) {
  const a = { app: "http://127.0.0.1:8501", api: "http://127.0.0.1:8000", out: path.join(DIR, "demo-frames") };
  for (let i = 0; i < argv.length; i += 2) a[argv[i].replace(/^--/, "")] = argv[i + 1];
  return a;
}

// Row of the customer in the churn table: same filter and order as frontend/views/risk.py.
async function tableRow(api, cid) {
  const all = [];
  for (let page = 1; ; page++) {
    const r = await (await fetch(`${api}/api/customers?page=${page}&page_size=200`)).json();
    all.push(...r.items);
    if (page >= r.total_pages) break;
  }
  const values = all.map((c) => c.churn_probability || 0).sort((a, b) => a - b);
  const high = values[Math.floor(0.75 * (values.length - 1))];
  const rows = all.filter((c) => (c.churn_probability || 0) >= high)
    .sort((a, b) => (b.churn_probability || 0) - (a.churn_probability || 0) || (b.current_clv_eur || 0) - (a.current_clv_eur || 0));
  const i = rows.findIndex((c) => c.customer_id === cid);
  if (i < 0) throw new Error(`${cid} is not in the churn table`);
  return i;
}

async function main() {
  const opts = args(process.argv.slice(2));
  fs.rmSync(opts.out, { recursive: true, force: true });
  fs.mkdirSync(opts.out, { recursive: true });

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: VIEW, deviceScaleFactor: 2 });
  const manifest = { viewport: VIEW, scale: 2, customer: CUSTOMER, question: QUESTION, clips: {} };
  let n = 0, clip = null;

  const start = (name) => { clip = manifest.clips[name] = { frames: [], boxes: {} }; };
  const shot = async () => {
    const file = `${String(n++).padStart(4, "0")}.jpg`;
    await page.screenshot({ path: path.join(opts.out, file), type: "jpeg", quality: 92 });
    clip.frames.push(file);
  };
  const box = async (name, locator) => {
    const b = await locator.first().boundingBox();
    if (!b) throw new Error(`not on screen: ${name}`);
    clip.boxes[name] = { x: +b.x.toFixed(1), y: +b.y.toFixed(1), w: +b.width.toFixed(1), h: +b.height.toFixed(1) };
    return clip.boxes[name];
  };
  const idle = async () => {
    await page.waitForTimeout(350);
    await page.waitForFunction(() => !document.querySelector('[data-stale="true"]') &&
      !document.querySelector('[data-testid="stStatusWidget"]') && !document.querySelector('[data-testid="stSpinner"]'),
      null, { timeout: 30000 });
    await page.waitForTimeout(700);
  };
  const scrollTo = async (selector, target, frames) => {
    const from = await page.$eval(selector, (el) => el.scrollTop);
    for (let i = 1; i <= frames; i++) {
      const p = i / frames, e = p < 0.5 ? 4 * p ** 3 : 1 - (-2 * p + 2) ** 3 / 2;
      await page.$eval(selector, (el, y) => { el.scrollTop = y; }, from + (target - from) * e);
      await page.waitForTimeout(30);
      await shot();
    }
  };
  const MAIN = '[data-testid="stMain"]';
  const GRID = ".dvn-scroller";
  const mainTop = () => page.$eval(MAIN, (el) => el.scrollTop);

  // 1 · churn risk page
  await page.goto(`${opts.app}/risk`);
  await page.getByText("customers are likely to cancel").waitFor();
  await idle();
  await page.mouse.move(980, 300);
  start("risk");
  await shot();
  await box("headline", page.locator("h1").filter({ hasText: "likely to cancel" }));
  await box("tiles", page.locator(".lt-tiles"));
  await box("grid", page.locator('[data-testid="stDataFrame"]'));

  // 2 · bring the whole table into view, then scroll the table to the customer
  const grid0 = await page.locator('[data-testid="stDataFrame"]').boundingBox();
  start("risk-scroll");
  await scrollTo(MAIN, grid0.y + grid0.height - VIEW.height + 24, 16);
  const grid = await box("grid", page.locator('[data-testid="stDataFrame"]'));
  const rowIndex = await tableRow(opts.api, CUSTOMER);
  const ROW = 35, HEAD = 35;
  await page.mouse.move(grid.x + grid.w * 0.45, grid.y + grid.h * 0.55);
  start("grid-scroll");
  const gridTarget = (rowIndex - 7) * ROW;
  await scrollTo(GRID, gridTarget, 16);
  const rowY = grid.y + HEAD + rowIndex * ROW - (await page.$eval(GRID, (el) => el.scrollTop)) + ROW / 2;
  clip.boxes.row = { x: grid.x, y: +(rowY - ROW / 2).toFixed(1), w: grid.w, h: ROW };
  clip.boxes.click = { x: grid.x + 18, y: +rowY.toFixed(1), w: 0, h: 0 };

  // 3 · select the customer's row: the churn card appears under the table
  await page.mouse.move(grid.x + 18, rowY, { steps: 4 });
  await page.mouse.click(grid.x + 18, rowY);
  await page.getByRole("button", { name: `Open ${CUSTOMER}` }).waitFor({ timeout: 15000 });
  await idle();
  start("row-selected");
  await shot();

  // 4 · scroll down to the churn card
  const card = page.locator("section.lt-card").filter({ hasText: "Will this customer cancel?" });
  const cardBox = await card.first().boundingBox();
  start("card-scroll");
  await scrollTo(MAIN, (await mainTop()) + cardBox.y - 40, 20);
  await box("card", card);
  await box("chance", card.getByText("chance to cancel within 12 months"));
  await box("why", card.getByText("Price guarantee ends within 90 days"));
  await box("open", page.getByRole("button", { name: `Open ${CUSTOMER}` }));

  // 5 · open the customer
  await page.getByRole("button", { name: `Open ${CUSTOMER}` }).click();
  await page.locator("h1").filter({ hasText: CUSTOMER }).waitFor();
  await idle();
  start("customer");
  await shot();

  // 6 · scroll to Lighty's recommendation
  const hero = page.locator(".lt-hero").first();
  const heroBox = await hero.boundingBox();
  start("hero-scroll");
  await scrollTo(MAIN, (await mainTop()) + heroBox.y - 60, 20);
  await box("hero", hero);
  await box("hero-title", page.locator(".lt-hero__title"));

  // 7 · scroll to Ask Lighty and type the question
  const ask = page.locator(".st-key-ask-lighty");
  const askBox = await ask.boundingBox();
  start("ask-scroll");
  await scrollTo(MAIN, (await mainTop()) + askBox.y - 70, 22);
  await box("ask", ask);
  const input = page.locator('[data-testid="stChatInputTextArea"]');
  await box("input", input);
  await input.click();
  start("typing");
  await shot();
  for (const ch of QUESTION) {
    await page.keyboard.type(ch);
    await shot();
  }
  await box("input", input);

  // 8 · send it and wait for Lighty's answer
  await page.keyboard.press("Enter");
  start("sending");
  for (let i = 0; i < 3; i++) { await page.waitForTimeout(60); await shot(); }
  await page.locator(".st-key-ask-lighty").getByText("12-month churn probability").first().waitFor({ timeout: 30000 });
  await idle();
  start("answer");
  await shot();
  const answer = page.locator(".st-key-ask-lighty").getByText("12-month churn probability").first();
  const ansBox = await answer.boundingBox();
  if (ansBox.y + ansBox.height > VIEW.height - 120 || ansBox.y < 80) {
    start("answer-scroll");
    await scrollTo(MAIN, (await mainTop()) + ansBox.y - 300, 20);
  }
  await box("ask", ask);
  await box("answer-churn", answer);
  await box("answer-price", page.locator(".st-key-ask-lighty").getByText(/^The price guarantee ends on/).first());
  await box("question", page.locator(".st-key-ask-lighty").getByText(QUESTION).first());

  fs.writeFileSync(path.join(opts.out, "manifest.json"), JSON.stringify(manifest, null, 1));
  console.log(`${n} frames → ${opts.out}`);
  for (const [k, c] of Object.entries(manifest.clips)) console.log(`  ${k.padEnd(13)} ${String(c.frames.length).padStart(3)} frames  ${Object.keys(c.boxes).join(", ")}`);
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
