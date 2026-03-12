/** Typed client for the hudukaata search server (matches its OpenAPI schema). */

/** A single result returned by GET /search */
export interface SearchResult {
  id: string
  caption: string
  relative_path: string
  extra: Record<string, string>
}

let _apiBase: string | null = null

export function setApiBase(url: string): void {
  _apiBase = url
}

export function getApiBase(): string {
  if (_apiBase === null) {
    _apiBase = (import.meta.env.VITE_API_URL as string | undefined) ?? ''
  }
  return _apiBase
}

/**
 * Call GET /search?q=&n= on the search server.
 * Throws if the server responds with a non-2xx status.
 */
export async function search(q: string, n?: number): Promise<SearchResult[]> {
  const url = new URL(`${getApiBase()}/search`)
  url.searchParams.set('q', q)
  if (n !== undefined) url.searchParams.set('n', String(n))

  const res = await fetch(url.toString())
  if (!res.ok) {
    throw new Error(`Search failed: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<SearchResult[]>
}

/** Return the URL for a media file served by GET /media/{path}. */
export function mediaUrl(relativePath: string): string {
  return `${getApiBase()}/media/${relativePath}`
}
