import { FaceResult, mediaUrl } from '../api'

interface Props {
  faces: FaceResult[]
  selectedFaceIds: string[]
  onToggle: (clusterId: string) => void
}

export default function FaceRibbon({ faces, selectedFaceIds, onToggle }: Props) {
  if (faces.length === 0) return null

  return (
    <nav aria-label="face filter">
      <ul style={{ display: 'flex', overflowX: 'auto', listStyle: 'none', padding: 0, gap: 8 }}>
        {faces.map((face) => {
          const selected = selectedFaceIds.includes(face.cluster_id)
          return (
            <li key={face.cluster_id}>
              <button
                type="button"
                aria-pressed={selected}
                aria-label={`Face cluster ${face.cluster_id} (${face.count} photos)`}
                onClick={() => onToggle(face.cluster_id)}
                style={{ outline: selected ? '2px solid blue' : undefined }}
              >
                <img
                  src={mediaUrl(face.representative_path)}
                  alt={`Face cluster representative`}
                  width={64}
                  height={64}
                  style={{ objectFit: 'cover', display: 'block' }}
                />
                <span>{face.count}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}
