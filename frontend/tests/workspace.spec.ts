import { test, expect } from '@playwright/test'

test('all workspaces render at desktop, tablet and phone widths without overflow', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  for (const width of [1440, 900, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    for (const path of [
      '/',
      '/studio/2',
      '/world',
      '/board',
      '/planner',
      '/reviews',
      '/timeline',
      '/runs',
      '/settings',
      '/wizard',
    ]) {
      await page.goto(path)
      await expect(page.locator('h1')).toBeVisible()
      await expect(page.locator('[aria-label="加载中"]')).toHaveCount(0)
      if (path === '/studio/2')
        await page.screenshot({ path: `test-results/studio-${width}.png`, fullPage: true })
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
        path + ' at ' + width,
      ).toBeTruthy()
    }
    await page.goto('/')
    await expect(page.getByRole('heading', { name: '欢迎回到你的故事' })).toBeVisible()
    await page.screenshot({
      path: `test-results/home-${width}.png`,
      fullPage: true,
    })
    if (width === 390) {
      await expect(page.getByRole('button', { name: '打开导航' })).toBeVisible()
      await page.getByRole('button', { name: '打开导航' }).click()
      await expect(page.getByRole('dialog')).toBeVisible()
      await page.getByRole('dialog').getByRole('link', { name: '世界观', exact: true }).click()
      await expect(page.getByRole('dialog')).toHaveCount(0)
    }
  }
  expect(errors).toEqual([])
})

test('a delayed previous-book response cannot replace the current chapter', async ({ page }) => {
  let ready!: () => void, release!: () => void
  const fetched = new Promise<void>((resolve) => {
    ready = resolve
  })
  const delayed = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/v1/chapter/2?*', async (route) => {
    if (new URL(route.request().url()).searchParams.get('book')) return route.continue()
    const response = await route.fetch()
    ready()
    await delayed
    await route.fulfill({ response }).catch(() => {}) // BookScope may already have aborted it.
  })
  await page.goto('/studio/2?mode=draft')
  await fetched
  await page.getByRole('combobox', { name: '切换书库' }).selectOption('second')
  await page.getByRole('link', { name: /继续创作/ }).click()
  await expect(page.getByText('她重新打开那段被删去的记忆。', { exact: true }).first()).toBeVisible()
  release()
  await expect(page.getByText('林昭握住剑柄，向前走了一步。', { exact: true })).toHaveCount(0)
  await expect(page).toHaveURL(/book=second/)
})

test('book switching and deep links never reuse another book content', async ({ page }) => {
  await page.goto('/studio/2?mode=draft')
  await expect(page.getByText('林昭握住剑柄，向前走了一步。', { exact: true }).first()).toBeVisible()
  await page.getByRole('combobox', { name: '切换书库' }).selectOption('second')
  await expect(page).toHaveURL(/book=second/)
  await expect(page.getByText('《删除线之下》', { exact: false })).toBeVisible()
  await page.goto('/studio/2?book=second&mode=draft')
  await expect(page.getByText('她重新打开那段被删去的记忆。', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('林昭握住剑柄，向前走了一步。', { exact: true })).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('combobox', { name: '切换书库' })).toHaveValue('second')
  await page.getByRole('combobox', { name: '切换书库' }).selectOption('')
  await expect(page.getByText('《青霜疑锋》', { exact: false })).toBeVisible()
})

test('a book named default does not share the implicit default workspace', async ({ page }) => {
  await page.request.post('/api/v1/books', { data: { name: 'default' } })
  await page.request.post('/api/v1/actions/blueprint_update?book=default', {
    data: { patch: { title: '显式同名书' } },
  })
  await page.goto('/')
  await page.getByRole('combobox', { name: '切换书库' }).selectOption('default')
  await expect(page.getByText('《显式同名书》', { exact: false })).toBeVisible()
  await expect(page.getByText('《青霜疑锋》', { exact: false })).toHaveCount(0)
  await page.getByRole('combobox', { name: '切换书库' }).selectOption('')
  await expect(page.getByText('《青霜疑锋》', { exact: false })).toBeVisible()
})

test('draft autosave, exact-version review, diff and navigation protection', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/studio/2?mode=draft')
  await page.getByRole('button', { name: '编辑草稿', exact: true }).click()
  const editor = page.getByRole('textbox', { name: '章节正文编辑器' })
  const original = await editor.inputValue()
  await editor.fill(original + '\n\n这是新增的一段。')
  await expect(page.getByText('未保存 · 停止输入 3 秒后自动保存')).toBeVisible()
  await expect(page.getByText(/已保存 · 自动保存时间/)).toBeVisible({
    timeout: 10000,
  })
  await expect(page.getByRole('combobox', { name: '草稿版本' })).toHaveValue('3')
  await page.getByRole('button', { name: '审校此版本' }).click()
  await expect(page.getByText('核对这里的人物动作')).toBeVisible({
    timeout: 10000,
  })
  await page.getByRole('button', { name: /核对这里的人物动作/ }).click()
  await expect(editor).toBeFocused()
  expect(
    await editor.evaluate((e: HTMLTextAreaElement) => e.selectionEnd - e.selectionStart),
  ).toBeGreaterThan(0)
  await page.getByRole('button', { name: '版本对比', exact: true }).click()
  await expect(page.locator('.diff-head').getByText('草稿 v3', { exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: '对比基准' }).selectOption('2')
  await expect(page.locator('.diff-row.changed').getByText('这是新增的一段。')).toBeVisible()
  await page.getByRole('button', { name: '草稿', exact: true }).click()
  await page.getByRole('button', { name: '编辑草稿', exact: true }).click()
  await editor.fill(original + '\n\n未保存的离开测试。')
  await page.getByRole('button', { name: '下一章' }).click()
  await expect(page.getByRole('dialog', { name: '正文尚未保存' })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: '取消', exact: true }).click()
  await expect(editor).toHaveValue(original + '\n\n未保存的离开测试。')
  await page.keyboard.press('Meta+s')
  await expect(page.getByText(/已保存 · 自动保存时间/)).toBeVisible()
})

test('filters and entity drawers survive refresh', async ({ page }) => {
  await page.goto('/world?book=second&entity=hero&type=Character&at=1')
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('heading', { name: '主角', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(page.getByRole('combobox', { name: '实体类型' })).toHaveValue('Character')
  await expect(page).toHaveURL(/book=second/)
})

test('save-and-leave during book switching writes only to the old book', async ({ page }) => {
  await page.goto('/studio/2?book=second&mode=draft')
  await page.getByRole('button', { name: '编辑草稿', exact: true }).click()
  const editor = page.getByRole('textbox', { name: '章节正文编辑器' })
  const saved = (await editor.inputValue()) + '\n\n只属于第二本书的修改。'
  await editor.fill(saved)
  await page.getByRole('combobox', { name: '切换书库' }).selectOption('')
  await expect(page.getByRole('dialog', { name: '正文尚未保存' })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: '保存并离开' }).click()
  await expect(page.getByText('《青霜疑锋》', { exact: false })).toBeVisible()
  const second = await (await page.request.get('/api/v1/chapter/2?book=second')).json()
  const draft = await (
    await page.request.get(`/api/v1/chapter/2/draft/${second.latest_draft_version}?book=second`)
  ).json()
  expect(draft.body).toBe(saved)
  const first = await (await page.request.get('/api/v1/chapter/2?book=')).json()
  const firstDraft = await (
    await page.request.get(`/api/v1/chapter/2/draft/${first.latest_draft_version}?book=`)
  ).json()
  expect(firstDraft.body).not.toContain('只属于第二本书')
})

test('restoring a historical draft creates a new unreviewed version', async ({ page }) => {
  const before = await (await page.request.get('/api/v1/chapter/2?book=')).json()
  await page.goto('/studio/2?mode=diff&version=2')
  await page.getByRole('button', { name: '恢复 v2 为新版本' }).click()
  await expect(page.getByRole('combobox', { name: '草稿版本' })).toHaveValue(
    String(before.latest_draft_version + 1),
  )
  await expect(page.getByRole('button', { name: '定稿入正典', exact: true })).toBeDisabled()
  const after = await (await page.request.get('/api/v1/chapter/2?book=')).json()
  expect(after.review_details).toEqual([])
  const latest = await (
    await page.request.get(`/api/v1/chapter/2/draft/${after.latest_draft_version}?book=`)
  ).json()
  expect(latest.parent_version).toBe(2)
  expect(latest.source).toBe('web_restore')
})

test('resume from home schedules a background run and opens its monitor', async ({ page }) => {
  await page.goto('/')
  const posted = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && response.url().includes('/jobs/novel_run_continue'),
  )
  await page.getByRole('button', { name: '恢复运行', exact: true }).click()
  expect((await posted).ok()).toBeTruthy()
  await expect(page).toHaveURL(/\/runs\/run_/)
  await expect(page.getByText('测试夹具已接收推进任务')).toBeVisible()
})

test('three-step architect interview, assumptions and change preview', async ({ page }) => {
  await page.goto('/wizard')
  await page.getByRole('textbox', { name: '故事创意' }).fill('一位记忆质检员寻找自己的故乡。')
  await page.getByRole('button', { name: /下一步 · AI 访谈/ }).click()
  await expect(page.getByRole('heading', { name: '1. 主角最想保护谁？' })).toBeVisible()
  await page.getByRole('button', { name: '家人', exact: true }).click()
  await page.getByRole('checkbox', { name: /我已确认/ }).check()
  await page.getByRole('button', { name: /生成故事蓝图/ }).click()
  await expect(page.getByRole('heading', { name: '回声之书', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认并应用蓝图' })).toBeDisabled()
  await page.getByRole('button', { name: '✓ 接受', exact: true }).click()
  await page.getByRole('textbox', { name: '新书库名称' }).fill('ui-created-book')
  await expect(page.getByRole('button', { name: '确认并应用蓝图' })).toBeEnabled()
  await page.reload()
  await expect(page.getByRole('heading', { name: '回声之书', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '确认并应用蓝图' }).click()
  await expect(page.getByRole('dialog', { name: '应用这份故事蓝图？' })).toBeVisible()
  await page.getByRole('dialog').getByRole('button', { name: '应用蓝图', exact: true }).click()
  await expect(page).toHaveURL(/\/planner\?book=ui-created-book/, {
    timeout: 15000,
  })
  await expect(page.getByRole('combobox', { name: '切换书库' })).toHaveValue('ui-created-book')
})
