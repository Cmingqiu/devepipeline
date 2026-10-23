import type { McpServerInput, McpTransport } from '@/api/contexts'

/** MCP 文本域的本地校验错误，message 直接展示给用户 */
export class McpConfigError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'McpConfigError'
  }
}

export interface McpServerLike {
  name: string
  transport: McpTransport
  config: Record<string, unknown>
  enabled: boolean
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return null
  }
  return value as Record<string, unknown>
}

function normalizeServer(raw: unknown, index: number, names: Set<string>): McpServerInput {
  const label = `第 ${index + 1} 个服务器`
  const record = asRecord(raw)
  if (!record) {
    throw new McpConfigError(`${label}必须是 JSON 对象`)
  }

  const name = typeof record.name === 'string' ? record.name.trim() : ''
  if (!name) {
    throw new McpConfigError(`${label}缺少 name`)
  }
  if (names.has(name)) {
    throw new McpConfigError(`服务器名称「${name}」重复`)
  }
  names.add(name)

  const transport = record.transport
  if (transport !== 'stdio' && transport !== 'streamable_http') {
    throw new McpConfigError(`服务器「${name}」的 transport 只能是 stdio 或 streamable_http`)
  }

  const config = asRecord(record.config)
  if (!config) {
    throw new McpConfigError(`服务器「${name}」缺少 config 对象`)
  }

  if (transport === 'stdio') {
    if (typeof config.command !== 'string' || !config.command.trim()) {
      throw new McpConfigError(`服务器「${name}」使用 stdio 时必须配置 config.command`)
    }
  } else if (typeof config.url !== 'string' || !config.url.trim()) {
    throw new McpConfigError(`服务器「${name}」使用 streamable_http 时必须配置 config.url`)
  }

  if (config.args !== undefined) {
    const args = config.args
    if (!Array.isArray(args) || args.some((arg) => typeof arg !== 'string')) {
      throw new McpConfigError(`服务器「${name}」的 config.args 必须是字符串数组`)
    }
  }

  for (const key of ['env', 'headers'] as const) {
    if (config[key] !== undefined && !asRecord(config[key])) {
      throw new McpConfigError(`服务器「${name}」的 config.${key} 必须是 JSON 对象`)
    }
  }

  const enabled = record.enabled
  if (enabled !== undefined && typeof enabled !== 'boolean') {
    throw new McpConfigError(`服务器「${name}」的 enabled 必须是布尔值`)
  }

  return {
    name,
    transport,
    config,
    enabled: enabled ?? true,
  }
}

/** 解析并校验 MCP 文本域；结构不合法时抛 McpConfigError（中文消息） */
export function parseMcpServers(text: string): McpServerInput[] {
  const trimmed = text.trim()
  if (!trimmed) {
    throw new McpConfigError('MCP 配置不能为空，请输入 {"servers":[...]}')
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    throw new McpConfigError('MCP 配置不是合法 JSON，请检查引号、括号与逗号')
  }

  const root = asRecord(parsed)
  if (!root) {
    throw new McpConfigError('MCP 配置必须是 JSON 对象，形如 {"servers":[...]}')
  }
  if (!Array.isArray(root.servers)) {
    throw new McpConfigError('MCP 配置缺少 servers 数组')
  }

  const names = new Set<string>()
  return root.servers.map((server, index) => normalizeServer(server, index, names))
}

/** 把已保存的服务器回填成文本域内容，去掉 id 与 last_test_*，掩码值原样保留 */
export function formatMcpServers(servers: McpServerLike[]): string {
  const payload = servers.map((server) => ({
    name: server.name,
    transport: server.transport,
    config: server.config,
    enabled: server.enabled,
  }))
  return JSON.stringify({ servers: payload }, null, 2)
}

/** 测试结果里的 tools 可能是字符串，也可能是 { name } 对象 */
export function mcpToolLabel(tool: unknown): string {
  if (typeof tool === 'string') {
    return tool
  }
  const record = asRecord(tool)
  if (record) {
    if (typeof record.name === 'string' && record.name) {
      return record.name
    }
    if (typeof record.title === 'string' && record.title) {
      return record.title
    }
  }
  return String(tool)
}
