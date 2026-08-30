import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('产品标识', () => {
  it('HTML 页面标题使用统一的中英文名称', () => {
    const html = readFileSync(path.join(process.cwd(), 'index.html'), 'utf8')
    expect(html).toContain('<title>求职投递助手 / Career Application Assistant</title>')
  })
})
