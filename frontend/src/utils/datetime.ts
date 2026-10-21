import dayjs from 'dayjs'

/** 后端时间一律 UTC ISO8601，这里按本地时区展示 */
export function formatDateTime(value?: string | null): string {
  if (!value) {
    return '-'
  }
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm') : '-'
}

export function formatDate(value?: string | null): string {
  if (!value) {
    return '-'
  }
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD') : '-'
}

/** 运行耗时：结束时间缺失时按当前时间计算（进行中） */
export function formatDuration(start?: string | null, end?: string | null): string {
  if (!start) {
    return '-'
  }
  const startMs = dayjs(start).valueOf()
  if (!Number.isFinite(startMs)) {
    return '-'
  }
  const endMs = end ? dayjs(end).valueOf() : Date.now()
  if (!Number.isFinite(endMs) || endMs < startMs) {
    return '-'
  }

  const totalSeconds = Math.round((endMs - startMs) / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  if (hours > 0) {
    return `${hours}h ${minutes}m`
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`
  }
  return `${seconds}s`
}
