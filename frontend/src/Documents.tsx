import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'

type WorkspaceDocument = {
  id: string
  filename: string
  status: 'processing' | 'ready' | 'failed'
  error: string | null
}

const documentsUrl = '/api/workspaces/launch/documents'

async function responseError(response: Response, fallback: string) {
  const body = await response.json().catch(() => null)
  return new Error(typeof body?.detail === 'string' ? body.detail : fallback)
}

export function Documents({ demoUser }: { demoUser: string }) {
  const [documents, setDocuments] = useState<WorkspaceDocument[] | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [listError, setListError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const picker = useRef<HTMLInputElement>(null)
  const activeUpload = useRef<AbortController | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let timer: number | undefined
    let shouldPoll = refresh > 0

    async function loadDocuments() {
      try {
        const response = await fetch(documentsUrl, {
          headers: { 'X-Demo-User': demoUser },
          signal: controller.signal,
        })
        if (response.status === 401 || response.status === 403) shouldPoll = false
        if (!response.ok) throw await responseError(response, 'Could not load documents. Try refreshing the page.')

        const next: WorkspaceDocument[] = await response.json()
        if (controller.signal.aborted) return
        shouldPoll = next.some(document => document.status === 'processing')
        setDocuments(next)
        setListError('')
      } catch (error) {
        if (controller.signal.aborted) return
        setListError(error instanceof TypeError ? 'Could not reach the API to load documents.' : (error as Error).message)
      }
      if (shouldPoll) timer = window.setTimeout(() => void loadDocuments(), 1000)
    }

    void loadDocuments()
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [demoUser, refresh])

  useEffect(() => () => activeUpload.current?.abort(), [])

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file || activeUpload.current) return
    const controller = new AbortController()
    activeUpload.current = controller
    setUploading(true)
    setUploadError('')

    const body = new FormData()
    body.append('file', file)
    try {
      const response = await fetch(documentsUrl, {
        method: 'POST',
        headers: { 'X-Demo-User': demoUser },
        body,
        signal: controller.signal,
      })
      if (!response.ok) throw await responseError(response, 'Could not upload this file. Try again.')
      if (controller.signal.aborted) return
      if (picker.current) picker.current.value = ''
      setFile(null)
      setRefresh(value => value + 1)
    } catch (error) {
      if (!controller.signal.aborted) {
        setUploadError(error instanceof TypeError ? 'Could not reach the API to upload this file.' : (error as Error).message)
      }
    } finally {
      activeUpload.current = null
      if (!controller.signal.aborted) setUploading(false)
    }
  }

  return (
    <section aria-labelledby="documents-heading">
      <h2 id="documents-heading">Documents</h2>
      <form onSubmit={upload}>
        <label htmlFor="document-file">Choose a PDF, PowerPoint (.pptx), or Excel (.xlsx) file</label>
        <div className="upload-controls">
          <input
            id="document-file"
            type="file"
            accept=".pdf,.pptx,.xlsx"
            ref={picker}
            disabled={uploading}
            onChange={event => setFile(event.target.files?.[0] ?? null)}
          />
          <button type="submit" disabled={!file || uploading}>
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        </div>
        {uploadError && <p role="alert">{uploadError}</p>}
      </form>
      {listError && <p role="alert">{listError}</p>}
      {!documents && !listError && <p role="status">Loading documents…</p>}
      <div aria-live="polite">
        {documents?.length === 0 && <p>No documents yet.</p>}
        {documents && documents.length > 0 && (
          <ul className="documents" aria-label="Workspace documents">
            {documents.map(document => (
              <li key={document.id}>
                <strong>{document.filename}</strong> · {document.status}
                {document.error && <p>{document.error}</p>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
