import { StrictMode, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { getApiBase, setApiBase, search, SearchResult } from './api'
import SearchBar from './components/SearchBar'
import ResultCard from './components/ResultCard'

export default function App() {
  const [apiUrl, setApiUrl] = useState<string>(getApiBase)
  const [results, setResults] = useState<SearchResult[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  function handleApiUrlChange(url: string) {
    setApiUrl(url)
    setApiBase(url)
  }

  async function handleSearch(query: string) {
    if (!apiUrl) {
      setError('Please set an API server URL before searching.')
      return
    }
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
      <label>
        API server
        <input
          type="url"
          value={apiUrl}
          onChange={(e) => handleApiUrlChange(e.target.value)}
        />
      </label>
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

const root = document.getElementById('root')
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}
