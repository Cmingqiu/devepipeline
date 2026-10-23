import { describe, expect, it } from 'vitest'

import type { McpServer } from '@/api/contexts'
import { formatMcpServers, mcpToolLabel, parseMcpServers } from '@/utils/mcp'

const VALID_TEXT = JSON.stringify({
  servers: [
    {
      name: 'filesystem',
      transport: 'stdio',
      config: {
        command: 'npx',
        args: ['-y', '@modelcontextprotocol/server-filesystem', '.'],
        env: { TOKEN: '****1234' },
      },
      enabled: true,
    },
    {
      name: 'remote',
      transport: 'streamable_http',
      config: {
        url: 'http://127.0.0.1:8931/mcp',
        headers: { Authorization: 'Bearer ****1234' },
      },
    },
  ],
})

function makeServer(overrides: Partial<McpServer> = {}): McpServer {
  return {
    id: 1,
    project_id: 9,
    name: 'filesystem',
    transport: 'stdio',
    config: { command: 'npx', env: { TOKEN: '****1234' } },
    enabled: true,
    last_test_status: 'ok',
    last_test_at: '2026-10-23T06:00:00.000Z',
    last_test_message: null,
    ...overrides,
  }
}

describe('utils/mcp MCP 文本域解析与校验', () => {
  it('合法 JSON 通过，缺省 enabled 按启用处理，掩码原样保留', () => {
    const servers = parseMcpServers(VALID_TEXT)

    expect(servers).toHaveLength(2)
    expect(servers[0]).toMatchObject({
      name: 'filesystem',
      transport: 'stdio',
      enabled: true,
    })
    expect(servers[0]?.config.env).toEqual({ TOKEN: '****1234' })
    expect(servers[1]).toMatchObject({
      name: 'remote',
      transport: 'streamable_http',
      enabled: true,
    })
    expect(servers[1]?.config.url).toBe('http://127.0.0.1:8931/mcp')
  })

  it('非 JSON 被拦截并给中文提示', () => {
    expect(() => parseMcpServers('{ "servers": [')).toThrowError(/不是合法 JSON/)
    expect(() => parseMcpServers('   ')).toThrowError(/不能为空/)
  })

  it('结构不对被拦截：缺 servers、transport 非法', () => {
    expect(() => parseMcpServers('[]')).toThrowError(/必须是 JSON 对象/)
    expect(() => parseMcpServers('{}')).toThrowError(/缺少 servers 数组/)
    expect(() =>
      parseMcpServers(
        JSON.stringify({
          servers: [{ name: 'x', transport: 'sse', config: { url: 'http://127.0.0.1' } }],
        }),
      ),
    ).toThrowError(/transport 只能是 stdio 或 streamable_http/)
  })

  it('stdio 缺 command、streamable_http 缺 url 分别被拦截', () => {
    expect(() =>
      parseMcpServers(
        JSON.stringify({ servers: [{ name: 'fs', transport: 'stdio', config: { args: [] } }] }),
      ),
    ).toThrowError(/必须配置 config\.command/)

    expect(() =>
      parseMcpServers(
        JSON.stringify({
          servers: [{ name: 'remote', transport: 'streamable_http', config: {} }],
        }),
      ),
    ).toThrowError(/必须配置 config\.url/)
  })

  it('config 不是对象、名称重复也会被拦截', () => {
    expect(() =>
      parseMcpServers(
        JSON.stringify({ servers: [{ name: 'fs', transport: 'stdio', config: 'npx' }] }),
      ),
    ).toThrowError(/缺少 config 对象/)

    expect(() =>
      parseMcpServers(
        JSON.stringify({
          servers: [
            { name: 'dup', transport: 'stdio', config: { command: 'npx' } },
            { name: 'dup', transport: 'stdio', config: { command: 'npx' } },
          ],
        }),
      ),
    ).toThrowError(/重复/)
  })

  it('formatMcpServers 去掉 id/last_test_*，只保留可编辑字段和掩码', () => {
    const text = formatMcpServers([makeServer()])
    const parsed = JSON.parse(text) as {
      servers: Array<Record<string, unknown>>
    }

    expect(parsed.servers).toHaveLength(1)
    expect(Object.keys(parsed.servers[0] ?? {}).sort()).toEqual([
      'config',
      'enabled',
      'name',
      'transport',
    ])
    expect(parsed.servers[0]?.config).toEqual({ command: 'npx', env: { TOKEN: '****1234' } })
    expect(text).not.toContain('last_test_status')
    expect(text).toContain('****1234')
  })

  it('mcpToolLabel 兼容字符串与 { name } 对象', () => {
    expect(mcpToolLabel('read_file')).toBe('read_file')
    expect(mcpToolLabel({ name: 'write_file' })).toBe('write_file')
    expect(mcpToolLabel({ title: '搜索' })).toBe('搜索')
  })
})
