import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SearchBar from '../components/SearchBar'

describe('SearchBar', () => {
  it('renders a search input and submit button', () => {
    render(<SearchBar onSearch={vi.fn()} />)
    expect(screen.getByRole('searchbox')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /search/i })).toBeInTheDocument()
  })

  it('button is disabled when input is empty', () => {
    render(<SearchBar onSearch={vi.fn()} />)
    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('button becomes enabled when text is typed', async () => {
    render(<SearchBar onSearch={vi.fn()} />)
    await userEvent.type(screen.getByRole('searchbox'), 'cats')
    expect(screen.getByRole('button')).not.toBeDisabled()
  })

  it('calls onSearch with the trimmed query on submit', async () => {
    const onSearch = vi.fn()
    render(<SearchBar onSearch={onSearch} />)
    await userEvent.type(screen.getByRole('searchbox'), '  cats  ')
    await userEvent.click(screen.getByRole('button'))
    expect(onSearch).toHaveBeenCalledOnce()
    expect(onSearch).toHaveBeenCalledWith('cats')
  })

  it('does not call onSearch when the query is only whitespace', async () => {
    const onSearch = vi.fn()
    render(<SearchBar onSearch={onSearch} />)
    await userEvent.type(screen.getByRole('searchbox'), '   ')
    await userEvent.keyboard('{Enter}')
    expect(onSearch).not.toHaveBeenCalled()
  })

  it('disables both input and button when disabled prop is true', () => {
    render(<SearchBar onSearch={vi.fn()} disabled />)
    expect(screen.getByRole('searchbox')).toBeDisabled()
    expect(screen.getByRole('button')).toBeDisabled()
  })
})
