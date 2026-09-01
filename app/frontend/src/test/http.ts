export function jsonBody(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

export function okBody(body: unknown): Response {
  return {
    ok: true,
    status: 201,
    text: async () => JSON.stringify(body),
  } as unknown as Response
}

export const STANDARD_HEALTH = {
  status: 'ok',
  database: 'ready',
  schema_version: 4,
  service: 'career-application-assistant',
  mode: 'standard',
  synthetic_data: false,
  mail_ingestion: true,
} as const

export const DEMO_HEALTH = {
  ...STANDARD_HEALTH,
  mode: 'demo',
  synthetic_data: true,
  mail_ingestion: false,
} as const
