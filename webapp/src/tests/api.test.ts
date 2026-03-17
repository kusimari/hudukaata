import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { search, getFaces, mediaUrl } from '../api'

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

  it('includes face_ids parameter when provided', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response)

    await search('people', undefined, ['c1', 'c2'])

    const url = new URL(vi.mocked(fetch).mock.calls[0][0] as string)
    expect(url.searchParams.get('face_ids')).toBe('c1,c2')
  })

  it('omits face_ids when empty array', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response)

    await search('cats', undefined, [])

    const url = new URL(vi.mocked(fetch).mock.calls[0][0] as string)
    expect(url.searchParams.has('face_ids')).toBe(false)
  })

  it('returns parsed results', async () => {
    const results = [
      {
        id: '1',
        caption: 'A cat',
        relative_path: 'cat.jpg',
        face_cluster_ids: [],
        extra: {},
      },
    ]
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

describe('getFaces()', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('calls /faces endpoint', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response)

    await getFaces()

    const url = new URL(vi.mocked(fetch).mock.calls[0][0] as string)
    expect(url.pathname).toBe('/faces')
  })

  it('passes n parameter when provided', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response)

    await getFaces(10)

    const url = new URL(vi.mocked(fetch).mock.calls[0][0] as string)
    expect(url.searchParams.get('n')).toBe('10')
  })

  it('returns empty array on 404 (face store not loaded)', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: 'Not Found',
    } as Response)

    const result = await getFaces()
    expect(result).toEqual([])
  })

  it('returns parsed face results', async () => {
    const faces = [
      {
        cluster_id: 'uuid-1',
        representative_path: 'img1.jpg',
        count: 5,
        image_paths: ['img1.jpg', 'img2.jpg'],
        score: 1.0,
      },
    ]
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => faces,
    } as Response)

    const data = await getFaces()
    expect(data).toEqual(faces)
  })

  it('throws on non-2xx non-404 status', async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Server Error',
    } as Response)

    await expect(getFaces()).rejects.toThrow('500')
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
