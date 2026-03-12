import { useState, FormEvent } from 'react'

interface Props {
  onSearch: (query: string) => void
  disabled?: boolean
}

export default function SearchBar({ onSearch, disabled = false }: Props) {
  const [value, setValue] = useState('')

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = value.trim()
    if (trimmed) onSearch(trimmed)
  }

  return (
    <form onSubmit={handleSubmit} role="search">
      <input
        type="search"
        aria-label="Search query"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Search…"
        disabled={disabled}
      />
      <button type="submit" disabled={disabled || value.trim() === ''}>
        Search
      </button>
    </form>
  )
}
