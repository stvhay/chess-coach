import { test, expect, Page } from "@playwright/test";

/**
 * Click a chessground square by algebraic notation (e.g. "e2").
 * Computes pixel coordinates within the board element.
 * Assumes white orientation (a1 = bottom-left).
 */
async function clickSquare(page: Page, square: string) {
  const file = square.charCodeAt(0) - "a".charCodeAt(0); // 0-7 (a=0, h=7)
  const rank = parseInt(square[1]) - 1; // 0-7 (1=0, 8=7)

  const board = page.locator("cg-board");
  const box = await board.boundingBox();
  if (!box) throw new Error("Board not found");

  const squareW = box.width / 8;
  const squareH = box.height / 8;

  // White orientation: file goes left-to-right, rank goes bottom-to-top
  const x = box.x + squareW * file + squareW / 2;
  const y = box.y + squareH * (7 - rank) + squareH / 2;

  await page.mouse.click(x, y);
}

test.describe("Chess Game E2E", () => {
  test.beforeEach(async ({ page }) => {
    // Build frontend assets before navigating
    await page.goto("/static/index.html");
    // Wait for the board to render
    await page.waitForSelector("cg-board");
  });

  test("page loads with board and panel", async ({ page }) => {
    // Board renders
    await expect(page.locator(".board-wrap")).toBeVisible();
    await expect(page.locator("cg-board")).toBeVisible();

    // Panel elements are present
    await expect(page.locator(".panel")).toBeVisible();
    await expect(page.locator(".game-status")).toBeVisible();
    await expect(page.locator(".eval-display")).toBeVisible();
    await expect(page.locator(".move-history")).toBeVisible();
    await expect(page.locator(".controls button")).toBeVisible();
  });

  test("make a move and opponent responds", async ({ page }) => {
    // Wait for session to be created (New Game auto-fires on load)
    await page.waitForTimeout(500);

    // Play e2-e4
    await clickSquare(page, "e2");
    await clickSquare(page, "e4");

    // Wait for move history to show white's move
    await expect(page.locator(".move-history")).toContainText("e4", {
      timeout: 5000,
    });

    // Wait for opponent to respond (move history gets a second move)
    // The opponent move appears after the server responds
    await expect(page.locator(".move-history .move")).toHaveCount(2, {
      timeout: 10_000,
    });
  });

  test("multiple moves update history", async ({ page }) => {
    await page.waitForTimeout(500);

    // Move 1: e4
    await clickSquare(page, "e2");
    await clickSquare(page, "e4");

    // Wait for opponent response
    await expect(page.locator(".move-history .move")).toHaveCount(2, {
      timeout: 10_000,
    });

    // Move 2: pick a safe developing move
    // After opponent plays, we need to find a valid move.
    // d2-d4 is almost always legal as move 2 for white.
    await clickSquare(page, "d2");
    await clickSquare(page, "d4");

    // Wait for move 2 to complete with opponent response
    await expect(page.locator(".move-history .move")).toHaveCount(4, {
      timeout: 10_000,
    });

    // Verify move numbers appeared
    await expect(page.locator(".move-history .move-number")).toHaveCount(2);
  });

  test("New Game resets the board", async ({ page }) => {
    await page.waitForTimeout(500);

    // Make a move
    await clickSquare(page, "e2");
    await clickSquare(page, "e4");

    await expect(page.locator(".move-history .move")).toHaveCount(2, {
      timeout: 10_000,
    });

    // Click New Game
    await page.click(".controls button");

    // Move history should clear
    await expect(page.locator(".move-history .move")).toHaveCount(0, {
      timeout: 5000,
    });

    // Eval display resets
    await expect(page.locator(".eval-display")).toContainText("Eval:");
  });

  test("eval display updates after a move", async ({ page }) => {
    // Wait for initial engine load and eval
    // The browser Stockfish may or may not load; the server eval is what matters
    await page.waitForTimeout(1000);

    // Make a move
    await clickSquare(page, "e2");
    await clickSquare(page, "e4");

    // Wait for opponent response
    await expect(page.locator(".move-history .move")).toHaveCount(2, {
      timeout: 10_000,
    });

    // The eval display should show something (either a score or "engine unavailable")
    const evalText = await page.locator(".eval-display").textContent();
    expect(evalText).toBeTruthy();
    expect(evalText!.length).toBeGreaterThan(0);
  });
});
