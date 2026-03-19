/** Typed client for the hudukaata search server (matches its OpenAPI schema). */

/** A single result returned by GET /search */
export interface SearchResult {
  id: string
  caption: string
  relative_path: string
  face_cluster_ids: string[]
  extra: Record<string, string>
}

/** A single face cluster returned by GET /faces */
export interface FaceResult {
  cluster_id: string
  representative_path: string
  count: number
  image_paths: string[]
  score: number
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
 * Call GET /search?q=&n=&face_ids= on the search server.
 * Throws if the server responds with a non-2xx status.
 */
export async function search(
  q: string,
  n?: number,
  faceIds?: string[],
): Promise<SearchResult[]> {
  const url = new URL(`${getApiBase()}/search`)
  url.searchParams.set('q', q)
  if (n !== undefined) url.searchParams.set('n', String(n))
  if (faceIds && faceIds.length > 0) url.searchParams.set('face_ids', faceIds.join(','))

  const res = await fetch(url.toString())
  if (!res.ok) {
    throw new Error(`Search failed: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<SearchResult[]>
}

/**
 * Call GET /faces?n= on the search server.
 * Returns an empty array if the server returns 404 (face store not loaded).
 */
export async function getFaces(n?: number): Promise<FaceResult[]> {
  const url = new URL(`${getApiBase()}/faces`)
  if (n !== undefined) url.searchParams.set('n', String(n))

  const res = await fetch(url.toString())
  if (res.status === 404) return []
  if (!res.ok) {
    throw new Error(`Faces failed: ${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<FaceResult[]>
}

/** Return the URL for a media file served by GET /media/{path}. */
export function mediaUrl(relativePath: string): string {
  return `${getApiBase()}/media/${relativePath}`
}
