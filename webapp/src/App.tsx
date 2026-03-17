import { StrictMode, useCallback, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { FaceResult, SearchResult, getApiBase, getFaces, search, setApiBase } from './api'
import FaceRibbon from './components/FaceRibbon'
import ResultCard from './components/ResultCard'
import SearchBar from './components/SearchBar'

export default function App() {
  const [apiUrl, setApiUrl] = useState<string>(getApiBase)
  const [results, setResults] = useState<SearchResult[]>([])
  const [faces, setFaces] = useState<FaceResult[]>([])
  const [selectedFaceIds, setSelectedFaceIds] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  function handleApiUrlChange(url: string) {
    setApiUrl(url)
    setApiBase(url)
  }

  // Load face clusters whenever the API URL is set.
  useEffect(() => {
    if (!apiUrl) return
    getFaces().then(setFaces).catch(() => setFaces([]))
  }, [apiUrl])

  function handleFaceToggle(clusterId: string) {
    setSelectedFaceIds((prev) =>
      prev.includes(clusterId) ? prev.filter((id) => id !== clusterId) : [...prev, clusterId],
    )
  }

  const handleSearch = useCallback(
    async (query: string) => {
      if (!apiUrl) {
        setError('Please set an API server URL before searching.')
        return
      }
      setLoading(true)
      setError(null)
      try {
        const data = await search(query, undefined, selectedFaceIds)
        setResults(data)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Search failed')
        setResults([])
      } finally {
        setLoading(false)
      }
    },
    [apiUrl, selectedFaceIds],
  )

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
      <FaceRibbon
        faces={faces}
        selectedFaceIds={selectedFaceIds}
        onToggle={handleFaceToggle}
      />
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
