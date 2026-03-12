import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { search, mediaUrl } from '../api'

describe('search()', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('calls /search with the q parameter', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response)

    await search('cats')

    expect(fetch).toHaveBeenCalledOnce()
    const url = new URL(vi.mocked(fetch).mock.calls[0][0] as string)
    expect(url.pathname).toBe('/search')
    expect(url.searchParams.get('q')).toBe('cats')
  })

  it('omits n parameter when not provided', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response)

    await search('cats')

    const url = new URL(vi.mocked(fetch).mock.calls[0][0] as string)
    expect(url.searchParams.has('n')).toBe(false)
  })

  it('includes n parameter when provided', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response)

    await search('dogs', 5)

    const url = new URL(vi.mocked(fetch).mock.calls[0][0] as string)
    expect(url.searchParams.get('n')).toBe('5')
  })

  it('returns parsed results', async () => {
    const results = [{ id: '1', caption: 'A cat', relative_path: 'cat.jpg', extra: {} }]
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => results,
    } as Response)

    const data = await search('cats')
    expect(data).toEqual(results)
  })

  it('throws when the server returns a non-2xx status', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 422,
      statusText: 'Unprocessable Entity',
    } as Response)

    await expect(search('bad')).rejects.toThrow('422')
  })
})

describe('mediaUrl()', () => {
  it('returns the correct URL for a relative path', () => {
    expect(mediaUrl('photos/cat.jpg')).toMatch('photos/cat.jpg')
  })

  it('contains /media/ in the URL', () => {
    expect(mediaUrl('foo/bar.mp4')).toContain('/media/foo/bar.mp4')
  })
})
