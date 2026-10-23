import { mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it } from 'vitest'

import type { PullRequest } from '@/api/types'
import PullRequestPanel from '@/components/PullRequestPanel.vue'

const pullRequest: PullRequest = {
  id: 1,
  run_id: 7,
  provider: 'github',
  repo_full_name: 'acme/devpipeline',
  number: 12,
  url: 'https://github.com/acme/devpipeline/pull/12',
  branch: 'devpipeline/run-7',
  base_branch: 'main',
  head_sha: 'abc123def4567890',
  status: 'merged',
  created_at: '2026-10-23T06:00:00.000Z',
  updated_at: '2026-10-23T06:10:00.000Z',
}

const mountedWrappers: VueWrapper[] = []

function mountPanel(pullRequests: PullRequest[]): VueWrapper {
  const wrapper = mount(PullRequestPanel, {
    props: { pullRequests },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

afterEach(() => {
  while (mountedWrappers.length > 0) {
    mountedWrappers.pop()?.unmount()
  }
  document.body.innerHTML = ''
})

describe('PullRequestPanel PR 展示', () => {
  it('有 PR 时渲染编号、状态、分支与可点击链接', () => {
    const wrapper = mountPanel([pullRequest])

    const text = wrapper.text()
    expect(text).toContain('GitHub')
    expect(text).toContain('#12')
    expect(text).toContain('已合并')
    expect(text).toContain('acme/devpipeline')
    expect(text).toContain('devpipeline/run-7 → main')
    expect(text).toContain('head abc123de')
    expect(text).toContain('创建')

    const link = wrapper.find('a.pr-item__link')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe(pullRequest.url)
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toBe('noopener')
  })

  it('head_sha 为 null 时显示占位，不渲染空链接', () => {
    const wrapper = mountPanel([
      { ...pullRequest, head_sha: null, url: '', status: 'open' },
    ])

    expect(wrapper.text()).toContain('head -')
    expect(wrapper.text()).toContain('打开')
    expect(wrapper.find('a.pr-item__link').exists()).toBe(false)
  })

  it('没有 PR 时不渲染空卡片', () => {
    const wrapper = mountPanel([])

    expect(wrapper.find('section').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Pull Request')
  })
})
