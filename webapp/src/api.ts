/** Typed client for the hudukaata search server (matches its OpenAPI schema). */

/** A single result returned by GET /search */
export interface SearchResult {
  id: string
  caption: string
  relative_path: string
  extra: Record<string, string>
}

function apiBase(): string {
  return (import.meta.env.VITE_API_URL as string | undefined) ?? ''
}

/**
 * Call GET /search?q=&n= on the search server.
 * Throws if the server responds with a non-2xx status.
 */
export async function search(q: string, n?: number): Promise<SearchResult[]> {
  const url = new URL(`${apiBase()}/search`)
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
  return `${apiBase()}/media/${relativePath}`
}
