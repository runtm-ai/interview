import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Documents } from './Documents'
import './styles.css'

type User = { id: string; name: string }
type Workspace = { id: string; name: string; viewing_user: User; members: User[] }
type WorkspaceState =
  | { status: 'loading' }
  | { status: 'ready'; workspace: Workspace }
  | { status: 'error'; message: string }

function WorkspaceView({ demoUser }: { demoUser: string }) {
  const [state, setState] = useState<WorkspaceState>({ status: 'loading' })

  useEffect(() => {
    const controller = new AbortController()

    async function loadWorkspace() {
      try {
        const response = await fetch('/api/workspaces/launch', {
          headers: { 'X-Demo-User': demoUser },
          signal: controller.signal,
        })

        if (response.status === 401) {
          setState({ status: 'error', message: 'Choose Alice or Bob to open Launch.' })
          return
        }
        if (response.status === 403) {
          setState({ status: 'error', message: 'This user does not have access to Launch.' })
          return
        }
        if (!response.ok) {
          throw new Error('Workspace request failed')
        }

        const workspace: Workspace = await response.json()
        setState({ status: 'ready', workspace })
      } catch {
        if (!controller.signal.aborted) {
          setState({ status: 'error', message: 'Could not load Launch. Try refreshing the page.' })
        }
      }
    }

    void loadWorkspace()
    return () => controller.abort()
  }, [demoUser])

  return (
    <>
      <a className="back" href="/">← Choose a demo user</a>
      {state.status === 'loading' && <p role="status">Loading Launch…</p>}
      {state.status === 'error' && <p role="alert">{state.message}</p>}
      {state.status === 'ready' && (
        <>
          <h1>{state.workspace.name}</h1>
          <p className="viewer">Viewing as <strong>{state.workspace.viewing_user.name}</strong></p>
          <section aria-labelledby="members-heading">
            <h2 id="members-heading">Members</h2>
            <ul className="members">
              {state.workspace.members.map(member => (
                <li key={member.id}>{member.name}</li>
              ))}
            </ul>
          </section>
          <Documents key={demoUser} demoUser={demoUser} />
        </>
      )}
    </>
  )
}

function App() {
  const { pathname, search } = window.location
  const demoUser = new URLSearchParams(search).get('user') ?? ''

  return (
    <main className="workspace">
      {pathname === '/workspaces/launch' ? (
        <WorkspaceView demoUser={demoUser} />
      ) : (
        <>
          <h1>Open Launch</h1>
          <nav className="choices" aria-label="Demo users">
            <a href="/workspaces/launch?user=alice">Open as Alice</a>
            <a href="/workspaces/launch?user=bob">Open as Bob</a>
          </nav>
        </>
      )}
    </main>
  )
}

createRoot(document.getElementById('root')!).render(<App />)
