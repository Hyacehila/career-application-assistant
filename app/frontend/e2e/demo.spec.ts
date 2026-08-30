import { expect, test } from '@playwright/test'

test('Demo 标识、路由边界、写操作与页面重置保持一致', async ({ page, request }) => {
  const consoleIssues: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      consoleIssues.push(`${message.type()}: ${message.text()}`)
    }
  })
  page.on('pageerror', (error) => consoleIssues.push(`pageerror: ${error.message}`))

  await page.goto('/?view=mail')
  await expect(page).toHaveTitle('求职投递助手 / Career Application Assistant')
  await expect(page.getByTestId('demo-notice')).toContainText('合成演示数据')
  await expect(page).toHaveURL('http://127.0.0.1:8001/')
  await expect(page.getByRole('button', { name: '邮箱接入' })).toHaveCount(0)
  await expect(page.getByTestId(/^board-card-\d+$/)).toHaveCount(6)

  const created = await request.post('/api/applications', {
    data: {
      company_name: '虚构第七公司',
      job_title: '演示交互岗位',
      job_url: 'https://seventh-company.example.test/jobs/demo',
      event_date: '2026-08-30',
    },
  })
  expect(created.ok()).toBe(true)
  await page.reload()
  await expect(page.getByTestId(/^board-card-\d+$/)).toHaveCount(7)

  await page.getByTestId('demo-reset').click()
  await expect(page.getByText('演示数据已重置')).toBeVisible()
  await expect(page.getByTestId(/^board-card-\d+$/)).toHaveCount(6)
  expect(consoleIssues).toEqual([])
})
