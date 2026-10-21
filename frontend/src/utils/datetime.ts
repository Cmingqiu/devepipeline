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
