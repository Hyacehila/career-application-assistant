import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

const currentDirectory = path.dirname(fileURLToPath(import.meta.url))
const repositoryRoot = path.resolve(currentDirectory, '..', '..', '..')
const agentCommand = path.join(repositoryRoot, 'scripts', 'Invoke-BoardAgent.ps1')

function invokeAgent(arguments_: string[]) {
  const output = execFileSync(
    'pwsh',
    ['-NoProfile', '-File', agentCommand, ...arguments_],
    { cwd: repositoryRoot, encoding: 'utf8', timeout: 20_000 },
  )
  return JSON.parse(output)
}

test('fills, uploads, stops before final submit, and records pending review', async ({ page, request }) => {
  const consoleIssues: string[] = []
  const fixtureEmail = ['qa-candidate', 'example.test'].join('@')
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      consoleIssues.push(`${message.type()}: ${message.text()}`)
    }
  })
  page.on('pageerror', (error) => consoleIssues.push(`pageerror: ${error.message}`))

  await page.goto('/mock-recruitment?campaign=e2e#application')
  await expect(page).toHaveTitle('模拟招聘申请')
  await expect(page.getByRole('heading', { name: '软件工程实习生' })).toBeVisible()

  await page.getByLabel('姓名（必填）').fill('浏览器测试候选人')
  await page.getByLabel('邮箱（必填）').fill(fixtureEmail)
  await page.getByLabel('教育经历（必填）').fill('示例大学 · 软件工程 · 测试资料')
  await page.getByLabel('简历附件（必填）').setInputFiles({
    name: 'mock-resume.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4\n% browser regression fixture\n'),
  })
  await expect(page.getByLabel('简历附件（必填）')).toHaveValue(/mock-resume\.pdf$/)

  await page.getByRole('button', { name: '保存草稿' }).click()
  await expect(page.getByText('草稿已保存')).toBeVisible()
  await expect(page.locator('body')).toHaveAttribute('data-draft-save-count', '1')
  await expect(page.locator('body')).toHaveAttribute('data-final-submit-count', '0')
  await expect(page.getByRole('button', { name: '提交申请' })).toBeVisible()

  const metadata = page.getByTestId('job-metadata')
  const companyName = await metadata.getAttribute('data-company-name')
  const jobTitle = await metadata.getAttribute('data-job-title')
  const jobCode = await metadata.getAttribute('data-job-code')
  const location = await metadata.getAttribute('data-location')
  const source = await metadata.getAttribute('data-source')

  const recorded = invokeAgent([
    '-Action', 'FillCompleted',
    '-CompanyName', companyName ?? '',
    '-JobTitle', jobTitle ?? '',
    '-JobCode', jobCode ?? '',
    '-ApplicationType', '实习',
    '-Location', location ?? '',
    '-JobSource', source ?? '',
    '-JobUrl', page.url(),
    '-FilledAt', '2026-08-29T10:30:00+08:00',
  ])

  expect(recorded).toMatchObject({
    ok: true,
    action: 'fill_completed',
    current_status: 'pending_review',
  })
  expect(recorded.application_id).toEqual(expect.any(Number))

  const detailResponse = await request.get(`/api/applications/${recorded.application_id}`)
  expect(detailResponse.ok()).toBe(true)
  const detail = await detailResponse.json()
  expect(detail.application).toMatchObject({
    id: recorded.application_id,
    company_name: '示例招聘公司',
    job_title: '软件工程实习生',
    job_code: 'MOCK-001',
    current_status: 'pending_review',
    job_url: 'http://127.0.0.1:8000/mock-recruitment',
  })
  expect(detail.events).toHaveLength(1)
  expect(detail.events[0]).toMatchObject({ stage: 'pending_review', source: 'agent_fill' })

  const serializedDetail = JSON.stringify(detail)
  expect(serializedDetail).not.toContain('浏览器测试候选人')
  expect(serializedDetail).not.toContain(fixtureEmail)
  expect(serializedDetail).not.toContain('mock-resume.pdf')
  await expect(page.locator('body')).toHaveAttribute('data-final-submit-count', '0')
  expect(consoleIssues).toEqual([])
})
