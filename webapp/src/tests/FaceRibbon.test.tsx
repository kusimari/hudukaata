import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import FaceRibbon from '../components/FaceRibbon'
import type { FaceResult } from '../api'

const _face = (id: string, count: number = 3): FaceResult => ({
  cluster_id: id,
  representative_path: `${id}.jpg`,
  count,
  image_paths: [`${id}.jpg`],
  score: 1.0,
})

describe('FaceRibbon', () => {
  it('renders nothing when faces array is empty', () => {
    const { container } = render(
      <FaceRibbon faces={[]} selectedFaceIds={[]} onToggle={() => {}} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders a face filter nav with buttons for each cluster', () => {
    const faces = [_face('c1'), _face('c2')]
    render(<FaceRibbon faces={faces} selectedFaceIds={[]} onToggle={() => {}} />)

    expect(screen.getByRole('navigation', { name: /face filter/i })).toBeInTheDocument()
    const buttons = screen.getAllByRole('button')
    expect(buttons).toHaveLength(2)
  })

  it('shows count for each cluster', () => {
    const faces = [_face('c1', 7)]
    render(<FaceRibbon faces={faces} selectedFaceIds={[]} onToggle={() => {}} />)
    expect(screen.getByText('7')).toBeInTheDocument()
  })

  it('marks selected faces as pressed', () => {
    const faces = [_face('c1'), _face('c2')]
    render(<FaceRibbon faces={faces} selectedFaceIds={['c1']} onToggle={() => {}} />)

    const buttons = screen.getAllByRole('button')
    const c1btn = buttons.find((b) => b.getAttribute('aria-label')?.includes('c1'))
    const c2btn = buttons.find((b) => b.getAttribute('aria-label')?.includes('c2'))

    expect(c1btn).toHaveAttribute('aria-pressed', 'true')
    expect(c2btn).toHaveAttribute('aria-pressed', 'false')
  })

  it('calls onToggle with the cluster id when clicked', async () => {
    const onToggle = vi.fn()
    const faces = [_face('c1')]
    render(<FaceRibbon faces={faces} selectedFaceIds={[]} onToggle={onToggle} />)

    await userEvent.click(screen.getByRole('button'))
    expect(onToggle).toHaveBeenCalledWith('c1')
  })
})
