export function ok(data: unknown, status = 200): Response {
  return {
    ok: true,
    status,
    statusText: 'OK',
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
    blob: () => Promise.resolve(new Blob([JSON.stringify(data)])),
  } as unknown as Response
}

export function errResp(data: unknown, status: number): Response {
  return {
    ok: false,
    status,
    statusText: 'Error',
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
  } as unknown as Response
}

export function noContent(): Response {
  return {
    ok: true,
    status: 204,
    statusText: 'No Content',
    headers: new Headers({ 'content-length': '0' }),
    json: () => Promise.resolve(undefined),
    text: () => Promise.resolve(''),
  } as unknown as Response
}

export function blobResp(content: string, type = 'application/octet-stream'): Response {
  const blob = new Blob([content], { type })
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    headers: new Headers({ 'content-type': type }),
    blob: () => Promise.resolve(blob),
  } as unknown as Response
}

export function createSSEStream(lines: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  const full = lines.join('\n') + '\n'
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(full))
      controller.close()
    },
  })
}
