import { useState } from 'react'
import { search, SearchResult } from './api'
import SearchBar from './components/SearchBar'
import ResultCard from './components/ResultCard'

export default function App() {
  const [results, setResults] = useState<SearchResult[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSearch(query: string) {
    setLoading(true)
    setError(null)
    try {
      const data = await search(query)
      setResults(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Search failed')
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  return (
    <main>
      <h1>hudukaata</h1>
      <SearchBar onSearch={handleSearch} disabled={loading} />
      {loading && <p>Loading…</p>}
      {error !== null && <p role="alert">{error}</p>}
      <section aria-label="results">
        {results.map((r) => (
          <ResultCard key={r.id} result={r} />
        ))}
      </section>
    </main>
  )
}
