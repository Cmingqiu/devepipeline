import { flushPromises, mount, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it } from 'vitest'

import ProjectFormDialog from '@/components/ProjectFormDialog.vue'

const mountedWrappers: VueWrapper[] = []

function mountDialog(): ReturnType<typeof mount> {
  const wrapper = mount(ProjectFormDialog, {
    props: { modelValue: true },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

function findSubmitButton(wrapper: ReturnType<typeof mount>): DOMWrapper<Element> | undefined {
  return wrapper
    .findAll('button')
    .find((button) => button.text().includes('创建') || button.text().includes('保存'))
}

afterEach(() => {
  while (mountedWrappers.length > 0) {
    mountedWrappers.pop()?.unmount()
  }
  document.body.innerHTML = ''
})

describe('ProjectFormDialog', () => {
  it('name 为空时不 emit submit', async () => {
    const wrapper = mountDialog()
    await flushPromises()

    const submit = findSubmitButton(wrapper)
    expect(submit).toBeTruthy()

    await submit!.trigger('click')
    await flushPromises()

    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('填了 name 后 emit submit，带上名称', async () => {
    const wrapper = mountDialog()
    await flushPromises()

    const nameInput = wrapper.findAll('input')[0]
    expect(nameInput).toBeTruthy()
    await nameInput.setValue('演示项目')

    await findSubmitButton(wrapper)!.trigger('click')
    await flushPromises()

    const events = wrapper.emitted('submit')
    expect(events).toHaveLength(1)
    expect(events?.[0]?.[0]).toMatchObject({ name: '演示项目' })
  })

  it('编辑模式不显示 slug 输入，提交走更新载荷', async () => {
    const wrapper = mount(ProjectFormDialog, {
      props: {
        modelValue: true,
        project: {
          id: 1,
          name: '演示项目',
          slug: 'demo',
          description: null,
          status: 'active',
          created_at: '2026-10-21T06:00:00.000Z',
          updated_at: '2026-10-21T06:00:00.000Z',
        },
      },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    mountedWrappers.push(wrapper)
    await flushPromises()

    const inputs = wrapper.findAll('input')
    expect(inputs).toHaveLength(1)

    await findSubmitButton(wrapper)!.trigger('click')
    await flushPromises()

    const events = wrapper.emitted('submit')
    expect(events).toHaveLength(1)
    expect(events?.[0]?.[0]).toEqual({ name: '演示项目', description: null })
  })
})
