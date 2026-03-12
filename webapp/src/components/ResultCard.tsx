import { SearchResult, mediaUrl } from '../api'

const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.gif', '.webp', '.avif'])
const VIDEO_EXTS = new Set(['.mp4', '.webm', '.mov', '.mkv', '.avi'])

function extOf(path: string): string {
  const dot = path.lastIndexOf('.')
  return dot >= 0 ? path.slice(dot).toLowerCase() : ''
}

interface Props {
  result: SearchResult
}

export default function ResultCard({ result }: Props) {
  const ext = extOf(result.relative_path)
  const src = mediaUrl(result.relative_path)

  return (
    <article>
      {IMAGE_EXTS.has(ext) && (
        <img src={src} alt={result.caption} loading="lazy" />
      )}
      {VIDEO_EXTS.has(ext) && (
        <video src={src} controls aria-label={result.caption} />
      )}
      <p>{result.caption}</p>
    </article>
  )
}
