import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ResultCard from '../components/ResultCard'
import type { SearchResult } from '../api'

function makeResult(relative_path: string, caption = 'A caption'): SearchResult {
  return { id: '1', caption, relative_path, extra: {} }
}

describe('ResultCard', () => {
  it('renders an <img> for .jpg files', () => {
    render(<ResultCard result={makeResult('photo.jpg')} />)
    expect(screen.getByRole('img')).toBeInTheDocument()
  })

  it('renders an <img> for .png files', () => {
    render(<ResultCard result={makeResult('photo.png')} />)
    expect(screen.getByRole('img')).toBeInTheDocument()
  })

  it('renders a <video> for .mp4 files', () => {
    const { container } = render(<ResultCard result={makeResult('clip.mp4')} />)
    expect(container.querySelector('video')).toBeInTheDocument()
  })

  it('renders a <video> for .webm files', () => {
    const { container } = render(<ResultCard result={makeResult('clip.webm')} />)
    expect(container.querySelector('video')).toBeInTheDocument()
  })

  it('renders neither img nor video for unknown extensions', () => {
    const { container } = render(<ResultCard result={makeResult('data.csv')} />)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(container.querySelector('video')).not.toBeInTheDocument()
  })

  it('img src contains the relative path', () => {
    render(<ResultCard result={makeResult('albums/cat.jpg')} />)
    expect(screen.getByRole('img').getAttribute('src')).toContain('albums/cat.jpg')
  })

  it('video src contains the relative path', () => {
    const { container } = render(<ResultCard result={makeResult('clips/dog.mp4')} />)
    const video = container.querySelector('video')
    expect(video?.getAttribute('src')).toContain('clips/dog.mp4')
  })

  it('displays the caption text', () => {
    render(<ResultCard result={makeResult('photo.jpg', 'Sunset over mountains')} />)
    expect(screen.getByText('Sunset over mountains')).toBeInTheDocument()
  })

  it('uses caption as alt text on img', () => {
    render(<ResultCard result={makeResult('photo.jpg', 'My photo')} />)
    expect(screen.getByAltText('My photo')).toBeInTheDocument()
  })
})
