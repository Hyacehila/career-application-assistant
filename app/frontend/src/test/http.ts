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
