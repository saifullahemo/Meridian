import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatMessage } from './App';

type Project = {
  id: number;
  name: string;
  description?: string;
  instructions?: string;
  file_count?: number;
  artifact_count?: number;
  files?: ProjectFile[];
  artifacts?: ProjectArtifact[];
  memory?: ProjectMemory[];
};

type ProjectFile = {
  id: number;
  filename: string;
  status: string;
  enabled?: boolean;
  summary?: string;
  chars?: number;
  words?: number;
  warnings?: string[];
  created_at?: string;
};

type ProjectMemory = {
  id: number;
  content: string;
  kind?: string;
  created_at?: string;
};

type ProjectArtifact = {
  id: number;
  title: string;
  type: string;
  content: string;
  created_at?: string;
};

type SourceHit = {
  source?: string;
  title?: string;
  citation?: string;
  text?: string;
  score?: number;
};

async function readJson<T>(res: Response): Promise<T> {
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(String((json as any).detail || (json as any).message || `Request failed (${res.status})`));
  }
  return json as T;
}

export default function ProjectWorkspace({
  api,
  projects,
  activeProjectId,
  setActiveProjectId,
  onChanged,
}: {
  api: (path: string) => string;
  projects: Project[];
  activeProjectId: number | null;
  setActiveProjectId: (id: number | null) => void;
  onChanged: () => Promise<void>;
}) {
  const projectList = Array.isArray(projects) ? projects : [];
  const [project, setProject] = useState<Project | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState({ name: '', description: '', instructions: '' });
  const [editingSettings, setEditingSettings] = useState(false);
  const [sideTab, setSideTab] = useState<'files' | 'memory' | 'sources' | 'artifacts'>('files');
  const [instruction, setInstruction] = useState('');
  const [memoryDraft, setMemoryDraft] = useState('');
  const [sourceQuery, setSourceQuery] = useState('');
  const [sourceAnswer, setSourceAnswer] = useState('');
  const [sourceResults, setSourceResults] = useState<SourceHit[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  const loadProject = useCallback(async () => {
    if (!activeProjectId) {
      setProject(null);
      setMessages([]);
      return;
    }
    const detail = await readJson<{ project: Project }>(await fetch(api(`/api/projects/${activeProjectId}`)));
    const history = await readJson<{ history: any[] }>(await fetch(api(`/api/projects/${activeProjectId}/history`)));
    setProject(detail.project);
    setDraft({
      name: detail.project.name || '',
      description: detail.project.description || '',
      instructions: detail.project.instructions || '',
    });
    setMessages((history.history || []).map((item: any) => ({
      role: item.role === 'user' ? 'user' : item.role === 'system' ? 'system' : 'assistant',
        content: String(item.content || ''),
        action: item.action,
        sources: [],
      })));
  }, [activeProjectId, api]);

  useEffect(() => {
    loadProject().catch((e) => setError(String(e.message || e)));
  }, [loadProject]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  async function createProject() {
    if (!draft.name.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const json = await readJson<{ project: Project }>(
        await fetch(api('/api/projects'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(draft),
        }),
      );
      await onChanged();
      setActiveProjectId(json.project.id);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function saveSettings() {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      const json = await readJson<{ project: Project }>(
        await fetch(api(`/api/projects/${project.id}`), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(draft),
        }),
      );
      setProject(json.project);
      setEditingSettings(false);
      await onChanged();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function deleteProject() {
    if (!project) return;
    if (!window.confirm(`Delete project "${project.name}" and its files/chat memory?`)) return;
    setLoading(true);
    setError(null);
    try {
      await readJson(
        await fetch(api(`/api/projects/${project.id}?confirm_name=${encodeURIComponent(project.name)}`), { method: 'DELETE' }),
      );
      setActiveProjectId(null);
      setProject(null);
      setMessages([]);
      await onChanged();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function uploadFilesOnly() {
    if (!project || !files.length) return;
    setLoading(true);
    setError(null);
    try {
      const fd = new FormData();
      files.forEach((file) => fd.append('files', file));
      await readJson(await fetch(api(`/api/projects/${project.id}/files`), { method: 'POST', body: fd }));
      clearFiles();
      await loadProject();
      await onChanged();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function sendMessage() {
    if (!project || !instruction.trim()) return;
    const text = instruction.trim();
    const userMessage: ChatMessage = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMessage]);
    setInstruction('');
    setLoading(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append('instruction', text);
      files.forEach((file) => fd.append('files', file));
      const json = await readJson<any>(
        await fetch(api(`/api/projects/${project.id}/chat`), {
          method: 'POST',
          body: fd,
        }),
      );
      clearFiles();
      const assistant: ChatMessage = {
        role: 'assistant',
        content: String(json.message || ''),
        success: Boolean(json.success),
        action: json.action,
        artifacts: json.meta?.artifacts || [],
        sources: json.meta?.sources || [],
      };
      setMessages((prev) => [...prev, assistant]);
      await loadProject();
      await onChanged();
    } catch (e: any) {
      const message = String(e.message || e);
      setMessages((prev) => [...prev, { role: 'assistant', content: message, success: false }]);
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  async function removeFile(fileId: number) {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      await readJson(await fetch(api(`/api/projects/${project.id}/files/${fileId}`), { method: 'DELETE' }));
      await loadProject();
      await onChanged();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function toggleFile(file: ProjectFile) {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      await readJson(
        await fetch(api(`/api/projects/${project.id}/files/${file.id}`), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: !file.enabled }),
        }),
      );
      await loadProject();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function addMemory() {
    if (!project || !memoryDraft.trim()) return;
    setLoading(true);
    setError(null);
    try {
      await readJson(
        await fetch(api(`/api/projects/${project.id}/memory`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: memoryDraft.trim(), kind: 'note' }),
        }),
      );
      setMemoryDraft('');
      await loadProject();
      await onChanged();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function removeMemory(memoryId: number) {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      await readJson(await fetch(api(`/api/projects/${project.id}/memory/${memoryId}`), { method: 'DELETE' }));
      await loadProject();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function searchSources() {
    if (!project || !sourceQuery.trim()) return;
    setLoading(true);
    setError(null);
    setSourceAnswer('');
    setSourceResults([]);
    try {
      const json = await readJson<any>(
        await fetch(api(`/api/projects/${project.id}/query`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: sourceQuery.trim(), top_k: 5, answer: true }),
        }),
      );
      setSourceAnswer(String(json.message || ''));
      setSourceResults(json.sources || json.results || []);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  function clearFiles() {
    setFiles([]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  if (!activeProjectId || !project) {
    return (
      <section className="projectWorkspace">
        <div className="projectCreate panel">
          <div className="panelHeader">
            <h2>Create Project</h2>
          </div>
          <label className="field">
            <span>Name</span>
            <input value={draft.name} onChange={(e) => {
              const value = e.currentTarget.value;
              setDraft((prev) => ({ ...prev, name: value }));
            }} placeholder="CNN code rewrite" />
          </label>
          <label className="field">
            <span>Goal</span>
            <textarea value={draft.description} onChange={(e) => {
              const value = e.currentTarget.value;
              setDraft((prev) => ({ ...prev, description: value }));
            }} placeholder="Upload Python code and research notes, then rewrite the model as a CNN." />
          </label>
          <label className="field">
            <span>Instructions</span>
            <textarea value={draft.instructions} onChange={(e) => {
              const value = e.currentTarget.value;
              setDraft((prev) => ({ ...prev, instructions: value }));
            }} placeholder="Explain changes clearly, cite uploaded files, and produce runnable code when possible." />
          </label>
          {error ? <div className="notice error">{error}</div> : null}
          <div className="formActions">
            <button className="btn primary" type="button" onClick={createProject} disabled={loading || !draft.name.trim()}>
              {loading ? 'Creating...' : 'Create Project'}
            </button>
          </div>
          {projectList.length ? (
            <div className="projectPicker">
              <span>Or open an existing project</span>
              {projectList.map((item) => (
                <button key={item.id} type="button" className="sourceRow" onClick={() => setActiveProjectId(item.id)}>
                  <strong>{item.name}</strong>
                  <span>{item.file_count || 0} files · {item.artifact_count || 0} artifacts</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      </section>
    );
  }

  return (
    <section className="projectWorkspace">
      <div className="projectMain panel">
        <div className="panelHeader">
          <div>
            <h2>{project.name}</h2>
            <p>{project.description || 'Chat with this project, upload files, and create new work from its context.'}</p>
          </div>
          <button className="btn secondary" type="button" onClick={() => setEditingSettings((value) => !value)}>
            Settings
          </button>
        </div>

        {editingSettings ? (
          <div className="projectSettings">
            <label className="field">
              <span>Name</span>
              <input value={draft.name} onChange={(e) => {
                const value = e.currentTarget.value;
                setDraft((prev) => ({ ...prev, name: value }));
              }} />
            </label>
            <label className="field">
              <span>Goal</span>
              <textarea value={draft.description} onChange={(e) => {
                const value = e.currentTarget.value;
                setDraft((prev) => ({ ...prev, description: value }));
              }} />
            </label>
            <label className="field">
              <span>Instructions</span>
              <textarea value={draft.instructions} onChange={(e) => {
                const value = e.currentTarget.value;
                setDraft((prev) => ({ ...prev, instructions: value }));
              }} />
            </label>
            <div className="formActions">
              <button className="btn secondary" type="button" onClick={() => setEditingSettings(false)}>Cancel</button>
              <button className="btn primary" type="button" onClick={saveSettings} disabled={loading}>Save</button>
              <button className="btn danger" type="button" onClick={deleteProject} disabled={loading}>Delete</button>
            </div>
          </div>
        ) : null}

        <div className="chat projectChat">
          {!messages.length ? (
            <div className="emptyState">
              Start by asking about this project or uploading documents.
              <div className="hint">Files stay attached to this project for future follow-up questions.</div>
            </div>
          ) : null}
          {messages.map((message, index) => (
            <div key={index} className={message.role === 'user' ? 'bubble user' : 'bubble assistant'}>
              {message.action && message.action !== 'project_chat' ? <div className="routePill">{message.action.replace(/_/g, ' ')}</div> : null}
              <div className="bubbleText">{message.content}</div>
              {message.sources?.length ? (
                <div className="sourceChips">
                  {message.sources.slice(0, 5).map((source: any, i: number) => (
                    <span key={i}>{source.citation || source.title || source.source}</span>
                  ))}
                </div>
              ) : null}
              {message.artifacts?.length ? (
                <div className="artifactList">
                  {message.artifacts.map((artifact: any) => (
                    <div className="artifact" key={artifact.id || artifact.title}>
                      <strong>{artifact.title || 'Generated document'}</strong>
                      <pre className="documentPreview">{artifact.content || ''}</pre>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
          {loading ? (
            <div className="bubble assistant">
              <div className="bubbleText">Working...</div>
            </div>
          ) : null}
          <div ref={endRef} />
        </div>

        {error ? <div className="notice error">{error}</div> : null}

        <div className="composer">
          <textarea
            className="textarea"
            value={instruction}
            onChange={(e) => setInstruction(e.currentTarget.value)}
            placeholder="Ask about this project, uploaded documents, code, or ask me to create something..."
            rows={3}
          />
          <div className="row">
            <input
              ref={fileInputRef}
              className="fileInput"
              type="file"
              multiple
              onChange={(e) => setFiles(e.currentTarget.files ? Array.from(e.currentTarget.files) : [])}
            />
            <button className="btn secondary" type="button" onClick={uploadFilesOnly} disabled={loading || !files.length}>
              Upload
            </button>
            <button className="btn primary" type="button" onClick={sendMessage} disabled={loading || !instruction.trim()}>
              Send
            </button>
          </div>
          {files.length ? (
            <div className="filePreview">
              {files.map((file) => <span className="fileChip" key={file.name}>{file.name}</span>)}
              <button className="btn secondary" type="button" onClick={clearFiles}>Clear</button>
            </div>
          ) : null}
        </div>
      </div>

      <aside className="projectSide">
        <div className="sideTabs">
          {(['files', 'memory', 'sources', 'artifacts'] as const).map((tab) => (
            <button key={tab} className={sideTab === tab ? 'active' : ''} type="button" onClick={() => setSideTab(tab)}>
              {tab[0].toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>

        {sideTab === 'files' ? (
        <div className="panel">
          <div className="panelHeader">
            <h2>Files</h2>
          </div>
          <div className="ragSourceList">
            {(project.files || []).map((file) => (
              <div className="sourceRow" key={file.id}>
                <strong>{file.filename}</strong>
                <span>{file.status} · {file.words || 0} words · {file.enabled ? 'used in chat' : 'disabled'}</span>
                {file.summary ? <p>{file.summary}</p> : null}
                {file.warnings?.length ? <em>{file.warnings.join(' ')}</em> : null}
                <div className="sourceActions">
                  <button className="btn secondary" type="button" onClick={() => toggleFile(file)} disabled={loading}>
                    {file.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button className="btn secondary" type="button" onClick={() => removeFile(file.id)} disabled={loading}>Remove</button>
                </div>
              </div>
            ))}
            {!project.files?.length ? <div className="emptyState">No project files yet.</div> : null}
          </div>
        </div>
        ) : null}

        {sideTab === 'memory' ? (
        <div className="panel">
          <div className="panelHeader">
            <h2>Memory</h2>
          </div>
          <div className="sideForm">
            <textarea value={memoryDraft} onChange={(e) => setMemoryDraft(e.currentTarget.value)} placeholder="Add a fact, preference, or decision for this project" />
            <button className="btn primary" type="button" onClick={addMemory} disabled={loading || !memoryDraft.trim()}>Remember</button>
          </div>
          <div className="ragSourceList">
            {(project.memory || []).map((item) => (
              <div className="sourceRow" key={item.id}>
                <strong>{item.content}</strong>
                <span>{item.kind || 'note'} · {item.created_at || ''}</span>
                <button className="btn secondary" type="button" onClick={() => removeMemory(item.id)} disabled={loading}>Forget</button>
              </div>
            ))}
            {!project.memory?.length ? <div className="emptyState">No explicit project memory yet.</div> : null}
          </div>
        </div>
        ) : null}

        {sideTab === 'sources' ? (
        <div className="panel">
          <div className="panelHeader">
            <h2>Sources</h2>
          </div>
          <div className="sideForm">
            <textarea value={sourceQuery} onChange={(e) => setSourceQuery(e.currentTarget.value)} placeholder="Search this project's enabled files" />
            <button className="btn primary" type="button" onClick={searchSources} disabled={loading || !sourceQuery.trim()}>Search</button>
          </div>
          {sourceAnswer ? <div className="ragAnswer">{sourceAnswer}</div> : null}
          <div className="ragSourceList">
            {sourceResults.map((item, index) => (
              <div className="sourceRow" key={index}>
                <strong>{item.citation || item.title || item.source}</strong>
                <span>{item.score ? `score ${item.score}` : 'source match'}</span>
                {item.text ? <p>{item.text}</p> : null}
              </div>
            ))}
            {!sourceResults.length ? <div className="emptyState">Search results and citations will appear here.</div> : null}
          </div>
        </div>
        ) : null}

        {sideTab === 'artifacts' ? (
        <div className="panel">
          <div className="panelHeader">
            <h2>Artifacts</h2>
          </div>
          <div className="ragSourceList">
            {(project.artifacts || []).map((artifact) => (
              <div className="sourceRow" key={artifact.id}>
                <strong>{artifact.title}</strong>
                <span>{artifact.type} · {artifact.created_at || ''}</span>
              </div>
            ))}
            {!project.artifacts?.length ? <div className="emptyState">Generated documents will appear here.</div> : null}
          </div>
        </div>
        ) : null}
      </aside>
    </section>
  );
}
