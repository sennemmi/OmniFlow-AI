import { test, expect } from '@playwright/test';

test.describe('完整研发流水线闭环测试', () => {
  test('创建 Pipeline 并审批流转', async ({ page }) => {
    // 1. 进入控制台
    await page.goto('http://localhost:5173/console');
    await expect(page).toHaveTitle(/OmniFlow/);

    // 2. 创建 Pipeline
    await page.click('button:has-text("创建流水线")');
    await page.fill('input[placeholder*="输入需求"]', 'E2E 集成测试');
    await page.fill('textarea', '请帮我修改首页标题为 "Hello OmniFlow"');
    await page.click('button:has-text("创建流水线")');

    // 3. 验证进入详情页
    await expect(page).toHaveURL(/.*pipelines\/\d+/);
    
    // 4. 等待页面加载完成
    await page.waitForSelector('.pipeline-detail', { timeout: 5000 });

    // 5. 模拟人工审批（如果处于可审批状态）
    const approveButton = page.locator('button:has-text("批准")');
    if (await approveButton.isVisible().catch(() => false)) {
      await approveButton.click();
      await page.fill('textarea[placeholder*="审批意见"]', '同意修改');
      await page.click('button:has-text("确认批准")');
    }

    // 6. 验证状态显示
    await expect(page.locator('.status-badge')).toBeVisible();
  });

  test('Pipeline 列表页加载', async ({ page }) => {
    await page.goto('http://localhost:5173/console');
    
    // 验证页面元素
    await expect(page.locator('h1')).toContainText('控制台');
    await expect(page.locator('button:has-text("创建流水线")')).toBeVisible();
  });

  test('Pipeline 详情页导航', async ({ page }) => {
    // 先访问列表页
    await page.goto('http://localhost:5173/console');
    
    // 点击第一个 Pipeline（如果存在）
    const firstPipeline = page.locator('.pipeline-item').first();
    if (await firstPipeline.isVisible().catch(() => false)) {
      await firstPipeline.click();
      await expect(page).toHaveURL(/.*pipelines\/\d+/);
    }
  });
});
