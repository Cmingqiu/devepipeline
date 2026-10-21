import type { RunEvent, RunEventType } from '@/api/types'
import { stageLabel } from './stage'

export type EventTone = 'default' | 'info' | 'success' | 'warning' | 'danger'

export const RUN_EVENT_META: Record<RunEventType, { label: string; tone: EventTone }> = {
  run_started: { label: '运行开始', tone: 'info' },
  stage_started: { label: '阶段开始', tone: 'info' },
  llm_token: { label: 'Token', tone: 'default' },
  usage: { label: '用量', tone: 'info' },
  artifact_saved: { label: '产物保存', tone: 'success' },
  stage_finished: { label: '阶段完成', tone: 'success' },
  interrupt: { label: '等待审批', tone: 'warning' },
  decision: { label: '审批决策', tone: 'info' },
  error: { label: '错误', tone: 'danger' },
  run_finished: { label: '运行结束', tone: 'success' },
}

export function eventTypeLabel(type: string): string {
  return RUN_EVENT_META[type as RunEventType]?.label ?? type
}

export function eventTone(type: string): EventTone {
  return RUN_EVENT_META[type as RunEventType]?.tone ?? 'default'
}

export function truncateText(text: string, max = 60): string {
  if (text.length <= max) {
    return text
  }
  return `${text.slice(0, max)}…`
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** 时间线一行的摘要，按事件类型取关键字段并截断 */
export function formatEventSummary(
  type: string,
  payload: Record<string, unknown> = {},
): string {
  switch (type) {
    case 'run_started': {
      const status = text(payload.status) || 'queued'
      return payload.resumed ? `断点续跑（${status}）` : `开始运行（${status}）`
    }
    case 'stage_started':
      return `进入阶段：${stageLabel(text(payload.stage))}`
    case 'llm_token':
      return truncateText(text(payload.text), 40)
    case 'usage': {
      const prompt = num(payload.prompt_tokens) ?? 0
      const completion = num(payload.completion_tokens) ?? 0
      return `prompt ${prompt} / completion ${completion}`
    }
    case 'artifact_saved': {
      const id = num(payload.artifact_id)
      const version = num(payload.version)
      const kind = text(payload.kind)
      const summary = truncateText(text(payload.summary), 40)
      const prefix = `产物${id !== null ? ` #${id}` : ''}`
      const versionText = version !== null ? ` v${version}` : ''
      const kindText = kind ? ` ${kind}` : ''
      return summary ? `${prefix}${versionText}${kindText}：${summary}` : `${prefix}${versionText}${kindText}`
    }
    case 'stage_finished': {
      const stage = stageLabel(text(payload.stage))
      const duration = num(payload.duration_ms)
      return duration !== null ? `${stage}完成，耗时 ${duration} ms` : `${stage}完成`
    }
    case 'interrupt': {
      const label = text(payload.label) || stageLabel(text(payload.stage))
      const attempt = num(payload.attempt)
      return attempt !== null ? `等待审批：${label}（第 ${attempt} 次）` : `等待审批：${label}`
    }
    case 'decision': {
      const decision = text(payload.decision) || 'unknown'
      const feedback = truncateText(text(payload.feedback), 40)
      return feedback ? `决策 ${decision}：${feedback}` : `决策 ${decision}`
    }
    case 'error': {
      const code = text(payload.code)
      const message = text(payload.message)
      const body = [code, message].filter(Boolean).join(': ')
      return truncateText(body || '未知错误', 120)
    }
    case 'run_finished': {
      const status = text(payload.status) || 'unknown'
      const errorCode = text(payload.error_code)
      return errorCode ? `运行结束：${status}（${errorCode}）` : `运行结束：${status}`
    }
    default:
      return ''
  }
}

/** 时间线时间：HH:mm:ss */
export function formatEventTime(ts: string): string {
  if (!ts) {
    return '-'
  }
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) {
    return '-'
  }
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function eventStageLabel(event: RunEvent): string {
  return event.stage ? stageLabel(event.stage) : '-'
}
