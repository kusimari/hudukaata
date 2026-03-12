import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import * as api from '../api'

vi.mock('../api', async (importOriginal) => {
  const original = await importOriginal<typeof import('../api')>()
  return {
    ...original,
    search: vi.fn(),
  }
})

describe('App', () => {
  beforeEach(() => {
    vi.mocked(api.search).mockReset()
    api.setApiBase('http://localhost:8080')
  })

  it('renders the heading and search form', () => {
    render(<App />)
    expect(screen.getByText('hudukaata')).toBeInTheDocument()
    expect(screen.getByRole('searchbox')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /search/i })).toBeInTheDocument()
  })

  it('renders the api server url input', () => {
    render(<App />)
    expect(screen.getByLabelText(/api server/i)).toBeInTheDocument()
  })

  it('shows an error when searching with no api url set', async () => {
    render(<App />)
    await userEvent.clear(screen.getByLabelText(/api server/i))
    await userEvent.type(screen.getByRole('searchbox'), 'cats')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))
    expect(screen.getByRole('alert')).toHaveTextContent(/api server url/i)
  })

  it('calls search and renders result cards on submit', async () => {
    vi.mocked(api.search).mockResolvedValueOnce([
      { id: '1', caption: 'A cat', relative_path: 'cat.jpg', extra: {} },
      { id: '2', caption: 'A dog', relative_path: 'dog.jpg', extra: {} },
    ])

    render(<App />)
    await userEvent.type(screen.getByRole('searchbox'), 'animals')
    await userEvent.click(screen.getByRole('button', { name: /search/i }))

    await waitFor(() => expect(screen.getByText('A cat')).toBeInTheDocument())
    expect(screen.getByText('A dog')).toBeInTheDocument()
    expect(api.search).toHaveBeenCalledWith('animals')
  })

  it('shows an error alert when search rejects', async () => {
    vi.mocked(api.search).mockRejectedValueOnce(new Error('Network error'))

    render(<App />)
    await userEvent.type(screen.getByRole('searchbox'), 'fail')
    await userEvent.click(screen.getByRole('button'))

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Network error'),
    )
  })

  it('clears a previous error on a new search', async () => {
    vi.mocked(api.search)
      .mockRejectedValueOnce(new Error('First error'))
      .mockResolvedValueOnce([])

    render(<App />)
    const input = screen.getByRole('searchbox')

    await userEvent.type(input, 'first')
    await userEvent.click(screen.getByRole('button'))
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())

    await userEvent.clear(input)
    await userEvent.type(input, 'second')
    await userEvent.click(screen.getByRole('button'))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('shows a loading indicator while the search is in progress', async () => {
    let resolve!: (v: api.SearchResult[]) => void
    vi.mocked(api.search).mockReturnValueOnce(
      new Promise<api.SearchResult[]>((r) => {
        resolve = r
      }),
    )

    render(<App />)
    await userEvent.type(screen.getByRole('searchbox'), 'slow')
    await userEvent.click(screen.getByRole('button'))

    expect(screen.getByText(/loading/i)).toBeInTheDocument()

    resolve([])
    await waitFor(() => expect(screen.queryByText(/loading/i)).not.toBeInTheDocument())
  })

  it('replaces old results with new results on subsequent searches', async () => {
    vi.mocked(api.search)
      .mockResolvedValueOnce([{ id: '1', caption: 'First result', relative_path: 'a.jpg', extra: {} }])
      .mockResolvedValueOnce([{ id: '2', caption: 'Second result', relative_path: 'b.jpg', extra: {} }])

    render(<App />)
    const input = screen.getByRole('searchbox')

    await userEvent.type(input, 'first')
    await userEvent.click(screen.getByRole('button'))
    await waitFor(() => expect(screen.getByText('First result')).toBeInTheDocument())

    await userEvent.clear(input)
    await userEvent.type(input, 'second')
    await userEvent.click(screen.getByRole('button'))
    await waitFor(() => expect(screen.getByText('Second result')).toBeInTheDocument())
    expect(screen.queryByText('First result')).not.toBeInTheDocument()
  })
})
