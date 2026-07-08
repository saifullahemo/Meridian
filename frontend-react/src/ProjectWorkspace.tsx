import React, { useCallback, useEffect, useRef, useState } from 'react';
import type { ChatMessage } from './App';

type Project = {
  id: number;
  name: string;
  description?: string;
  instructions?: string;
  cover?: string;
  model_backend?: string;
  coding_model_backend?: string;
  archived?: boolean;
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
  is_final?: boolean;
  created_at?: string;
};

type ConversationState = {
  current_goal?: string;
  latest_file_name?: string;
  latest_artifact_title?: string;
  latest_action?: string;
  user_preferences?: string[];
  open_tasks?: string[];
  summary?: string;
  updated_at?: string;
};

type ModelStatus = {
  ai?: {
    ready?: boolean;
    active_backend?: string;
    model?: string;
    configured_backend?: string;
  };
  vector_store?: {
    provider?: string;
    enabled?: boolean;
  };
  embeddings?: {
    provider?: string;
    ready?: boolean;
  };
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
  const [draft, setDraft] = useState({ name: '', description: '', instructions: '', cover: '', model_backend: 'auto', coding_model_backend: 'auto' });
  const [editingSettings, setEditingSettings] = useState(false);
  const [sideTab, setSideTab] = useState<'files' | 'memory' | 'sources' | 'artifacts' | 'continuity'>('files');
  const [instruction, setInstruction] = useState('');
  const [memoryDraft, setMemoryDraft] = useState('');
  const [editingMemoryId, setEditingMemoryId] = useState<number | null>(null);
  const [sourceQuery, setSourceQuery] = useState('');
  const [sourceAnswer, setSourceAnswer] = useState('');
  const [sourceResults, setSourceResults] = useState<SourceHit[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [draggingFiles, setDraggingFiles] = useState(false);
  const [modelStatus, setModelStatus] = useState<ModelStatus | null>(null);
  const [artifactNotice, setArtifactNotice] = useState<string | null>(null);
  const [artifactDrafts, setArtifactDrafts] = useState<Record<number, { title: string; content: string }>>({});
  const [artifactVersions, setArtifactVersions] = useState<Record<number, any[]>>({});
  const [artifactRuns, setArtifactRuns] = useState<Record<number, any>>({});
  const [fileDetail, setFileDetail] = useState<any | null>(null);
  const [lastUserInstruction, setLastUserInstruction] = useState('');
  const [conversationState, setConversationState] = useState<ConversationState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const projectFileInputRef = useRef<HTMLInputElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  const loadProject = useCallback(async () => {
    if (!activeProjectId) {
      setProject(null);
      setMessages([]);
      return;
    }
    const detail = await readJson<{ project: Project }>(await fetch(api(`/api/projects/${activeProjectId}`)));
    const history = await readJson<{ history: any[] }>(await fetch(api(`/api/projects/${activeProjectId}/history`)));
    const state = await readJson<{ state: ConversationState }>(await fetch(api(`/api/projects/${activeProjectId}/conversation-state`)));
    setProject(detail.project);
    setConversationState(state.state || null);
    setDraft({
      name: detail.project.name || '',
      description: detail.project.description || '',
      instructions: detail.project.instructions || '',
      cover: detail.project.cover || '',
      model_backend: detail.project.model_backend || 'auto',
      coding_model_backend: detail.project.coding_model_backend || 'auto',
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
    fetch(api('/api/status'))
      .then((res) => readJson<ModelStatus>(res))
      .then((json) => setModelStatus(json))
      .catch(() => setModelStatus(null));
  }, [api]);

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

  async function archiveProject() {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      await readJson(
        await fetch(api(`/api/projects/${project.id}`), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ archived: true }),
        }),
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
    setLastUserInstruction(text);
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

  async function retryLastMessage() {
    if (!lastUserInstruction) return;
    setInstruction(lastUserInstruction);
    window.setTimeout(() => {
      const textarea = document.querySelector<HTMLTextAreaElement>('.composer textarea');
      textarea?.focus();
    }, 0);
  }

  function continueGeneration() {
    setInstruction('continue the code from the last line');
    window.setTimeout(() => {
      const textarea = document.querySelector<HTMLTextAreaElement>('.composer textarea');
      textarea?.focus();
    }, 0);
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

  async function useOnlyFile(file: ProjectFile) {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      await Promise.all((project.files || []).map((item) => fetch(api(`/api/projects/${project.id}/files/${item.id}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: item.id === file.id }),
      })));
      await loadProject();
      setInstruction(`Only use ${file.filename}: `);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function showFileDetail(file: ProjectFile) {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      const json = await readJson<any>(await fetch(api(`/api/projects/${project.id}/files/${file.id}`)));
      setFileDetail(json);
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
        await fetch(api(editingMemoryId ? `/api/projects/${project.id}/memory/${editingMemoryId}` : `/api/projects/${project.id}/memory`), {
          method: editingMemoryId ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: memoryDraft.trim(), kind: 'note' }),
        }),
      );
      setMemoryDraft('');
      setEditingMemoryId(null);
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

  function editMemory(item: ProjectMemory) {
    setEditingMemoryId(item.id);
    setMemoryDraft(item.content);
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

  async function checkArtifact(artifact: ProjectArtifact) {
    if (!project) return;
    setLoading(true);
    setError(null);
    setArtifactNotice(null);
    try {
      const json = await readJson<any>(
        await fetch(api(`/api/projects/${project.id}/artifacts/${artifact.id}/check`)),
      );
      setArtifactNotice(String(json.message || 'Artifact checked.'));
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function saveArtifact(artifact: ProjectArtifact) {
    if (!project) return;
    const draft = artifactDrafts[artifact.id] || { title: artifact.title, content: artifact.content };
    setLoading(true);
    setError(null);
    try {
      const json = await readJson<any>(
        await fetch(api(`/api/projects/${project.id}/artifacts/${artifact.id}`), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: draft.title, content: draft.content, note: 'Edited in project workspace' }),
        }),
      );
      setArtifactNotice('Artifact saved. Previous content is in version history.');
      setArtifactDrafts((prev) => ({ ...prev, [artifact.id]: { title: json.artifact.title, content: json.artifact.content } }));
      await loadProject();
      await onChanged();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function markArtifactFinal(artifact: ProjectArtifact) {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      await readJson(
        await fetch(api(`/api/projects/${project.id}/artifacts/${artifact.id}`), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ is_final: !artifact.is_final }),
        }),
      );
      await loadProject();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function loadArtifactVersions(artifact: ProjectArtifact) {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      const json = await readJson<any>(await fetch(api(`/api/projects/${project.id}/artifacts/${artifact.id}/versions`)));
      setArtifactVersions((prev) => ({ ...prev, [artifact.id]: json.versions || [] }));
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function repairArtifact(artifact: ProjectArtifact) {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      const json = await readJson<any>(
        await fetch(api(`/api/projects/${project.id}/artifacts/${artifact.id}/repair`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ instruction: 'Repair this generated code so it is complete and runnable.' }),
        }),
      );
      setArtifactNotice(json.code_quality?.ok ? 'Artifact repaired.' : 'Artifact repaired, but still has warnings.');
      setArtifactDrafts((prev) => ({ ...prev, [artifact.id]: { title: json.artifact.title, content: json.artifact.content } }));
      await loadProject();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function runArtifact(artifact: ProjectArtifact) {
    if (!project) return;
    setLoading(true);
    setError(null);
    try {
      const json = await readJson<any>(
        await fetch(api(`/api/projects/${project.id}/artifacts/${artifact.id}/run`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ timeout_seconds: 20 }),
        }),
      );
      setArtifactRuns((prev) => ({ ...prev, [artifact.id]: json.run }));
      setArtifactNotice(json.run?.success ? 'Code ran successfully.' : 'Code ran with errors. See output below.');
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function deleteArtifact(artifact: ProjectArtifact) {
    if (!project) return;
    if (!window.confirm(`Delete artifact "${artifact.title}"?`)) return;
    setLoading(true);
    setError(null);
    try {
      await readJson(await fetch(api(`/api/projects/${project.id}/artifacts/${artifact.id}`), { method: 'DELETE' }));
      setArtifactNotice('Artifact deleted.');
      await loadProject();
      await onChanged();
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function copyArtifact(artifact: ProjectArtifact) {
    try {
      await navigator.clipboard.writeText(artifact.content || '');
      setArtifactNotice('Artifact copied to clipboard.');
    } catch {
      setArtifactNotice('Copy failed. Select the artifact text and copy it manually.');
    }
  }

  function downloadArtifact(artifact: ProjectArtifact) {
    const extension = artifact.type === 'code' ? 'py' : 'md';
    const safeTitle = (artifact.title || 'artifact').replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^_+|_+$/g, '') || 'artifact';
    const blob = new Blob([artifact.content || ''], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = safeTitle.endsWith(`.${extension}`) ? safeTitle : `${safeTitle}.${extension}`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function clearFiles() {
    setFiles([]);
    if (fileInputRef.current) fileInputRef.current.value = '';
    if (projectFileInputRef.current) projectFileInputRef.current.value = '';
  }

  function addDroppedFiles(fileList: FileList | null) {
    if (!fileList) return;
    setFiles((prev) => [...prev, ...Array.from(fileList)]);
  }

  const enabledFiles = (project?.files || []).filter((file) => file.enabled).length;
  const unreadableFiles = (project?.files || []).filter((file) => file.status !== 'indexed').length;
  const backendName = modelStatus?.ai?.active_backend || 'none';
  const modelName = modelStatus?.ai?.model || 'not configured';
  const vectorProvider = modelStatus?.vector_store?.provider || modelStatus?.embeddings?.provider || 'local';

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
          <label className="field">
            <span>Cover / Focus</span>
            <input value={draft.cover} onChange={(e) => {
              const value = e.currentTarget.value;
              setDraft((prev) => ({ ...prev, cover: value }));
            }} placeholder="Stress prediction research, code rewrites, paper notes" />
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
            {project.cover ? <p className="projectCover">{project.cover}</p> : null}
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
            <label className="field">
              <span>Cover / Focus</span>
              <input value={draft.cover} onChange={(e) => {
                const value = e.currentTarget.value;
                setDraft((prev) => ({ ...prev, cover: value }));
              }} />
            </label>
            <label className="field">
              <span>General Model</span>
              <select value={draft.model_backend} onChange={(e) => {
                const value = e.currentTarget.value;
                setDraft((prev) => ({ ...prev, model_backend: value }));
              }}>
                <option value="auto">Auto fallback</option>
                <option value="groq">Groq</option>
                <option value="ollama">Ollama</option>
                <option value="openrouter">OpenRouter</option>
                <option value="gemini">Gemini</option>
              </select>
            </label>
            <label className="field">
              <span>Coding Model</span>
              <select value={draft.coding_model_backend} onChange={(e) => {
                const value = e.currentTarget.value;
                setDraft((prev) => ({ ...prev, coding_model_backend: value }));
              }}>
                <option value="auto">Auto fallback</option>
                <option value="groq">Groq</option>
                <option value="ollama">Ollama</option>
                <option value="openrouter">OpenRouter</option>
                <option value="gemini">Gemini</option>
              </select>
            </label>
            <div className="formActions">
              <button className="btn secondary" type="button" onClick={() => setEditingSettings(false)}>Cancel</button>
              <button className="btn primary" type="button" onClick={saveSettings} disabled={loading}>Save</button>
              <button className="btn secondary" type="button" onClick={archiveProject} disabled={loading}>Archive</button>
              <button className="btn danger" type="button" onClick={deleteProject} disabled={loading}>Delete</button>
            </div>
          </div>
        ) : null}

        <div className="projectDashboard">
          <div className="projectStat">
            <strong>{project.files?.length || 0}</strong>
            <span>{enabledFiles} enabled files</span>
          </div>
          <div className="projectStat">
            <strong>{project.memory?.length || 0}</strong>
            <span>project memories</span>
          </div>
          <div className="projectStat">
            <strong>{project.artifacts?.length || 0}</strong>
            <span>generated artifacts</span>
          </div>
          <div className={modelStatus?.ai?.ready ? 'projectStat online' : 'projectStat warning'}>
            <strong>{backendName}</strong>
            <span>{modelName}</span>
          </div>
          <div className="projectStat">
            <strong>{vectorProvider}</strong>
            <span>{unreadableFiles ? `${unreadableFiles} unreadable files` : 'retrieval ready'}</span>
          </div>
          <div className="projectStat">
            <strong>{conversationState?.latest_file_name || conversationState?.latest_artifact_title || 'none'}</strong>
            <span>continuity target</span>
          </div>
        </div>

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
                  <strong>Used sources</strong>
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
            <button className="btn secondary" type="button" onClick={retryLastMessage} disabled={loading || !lastUserInstruction}>
              Retry Last
            </button>
            <button className="btn secondary" type="button" onClick={continueGeneration} disabled={loading}>
              Continue
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
          {(['files', 'memory', 'sources', 'artifacts', 'continuity'] as const).map((tab) => (
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
          <div
            className={draggingFiles ? 'projectFileUpload dragging' : 'projectFileUpload'}
            onDragOver={(e) => {
              e.preventDefault();
              setDraggingFiles(true);
            }}
            onDragLeave={() => setDraggingFiles(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDraggingFiles(false);
              addDroppedFiles(e.dataTransfer.files);
            }}
          >
            <input
              ref={projectFileInputRef}
              className="fileInput"
              type="file"
              multiple
              onChange={(e) => setFiles(e.currentTarget.files ? Array.from(e.currentTarget.files) : [])}
            />
            <div className="fileUploadActions">
              <button className="btn primary" type="button" onClick={uploadFilesOnly} disabled={loading || !files.length}>
                {loading ? 'Uploading...' : 'Upload to Project'}
              </button>
              {files.length ? <button className="btn secondary" type="button" onClick={clearFiles}>Clear</button> : null}
            </div>
            {files.length ? (
              <div className="filePreview">
                {files.map((file) => <span className="fileChip" key={file.name}>{file.name}</span>)}
              </div>
            ) : (
              <div className="hint">Drop files here or choose files. Uploaded files stay with this project and are used in future project chat.</div>
            )}
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
                  <button className="btn secondary" type="button" onClick={() => useOnlyFile(file)} disabled={loading}>
                    Only Use This
                  </button>
                  <button className="btn secondary" type="button" onClick={() => showFileDetail(file)} disabled={loading}>
                    Preview
                  </button>
                  <button className="btn secondary" type="button" onClick={() => removeFile(file.id)} disabled={loading}>Remove</button>
                </div>
              </div>
            ))}
            {!project.files?.length ? <div className="emptyState">No project files yet.</div> : null}
          </div>
          {fileDetail ? (
            <div className="fileDetail">
              <div className="panelHeader">
                <h2>{fileDetail.file?.filename || 'File preview'}</h2>
                <button className="btn secondary" type="button" onClick={() => setFileDetail(null)}>Close</button>
              </div>
              <pre>{fileDetail.preview || 'No readable text extracted.'}</pre>
              {fileDetail.chunks?.length ? (
                <div className="chunkList">
                  {fileDetail.chunks.slice(0, 8).map((chunk: any) => (
                    <div className="chunkRow" key={chunk.index}>
                      <strong>Chunk {chunk.index}</strong>
                      <p>{chunk.text}</p>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
        ) : null}

        {sideTab === 'memory' ? (
        <div className="panel">
          <div className="panelHeader">
            <h2>Memory</h2>
          </div>
          <div className="sideForm">
            <textarea value={memoryDraft} onChange={(e) => setMemoryDraft(e.currentTarget.value)} placeholder="Add a fact, preference, or decision for this project" />
            <button className="btn primary" type="button" onClick={addMemory} disabled={loading || !memoryDraft.trim()}>
              {editingMemoryId ? 'Update Memory' : 'Remember'}
            </button>
            {editingMemoryId ? (
              <button className="btn secondary" type="button" onClick={() => {
                setEditingMemoryId(null);
                setMemoryDraft('');
              }}>Cancel Edit</button>
            ) : null}
          </div>
          <div className="ragSourceList">
            {(project.memory || []).map((item) => (
              <div className="sourceRow" key={item.id}>
                <strong>{item.content}</strong>
                <span>{item.kind || 'note'} · {item.created_at || ''}</span>
                <button className="btn secondary" type="button" onClick={() => editMemory(item)} disabled={loading}>Edit</button>
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
          {artifactNotice ? <div className="notice">{artifactNotice}</div> : null}
          <div className="ragSourceList">
            {(project.artifacts || []).map((artifact) => (
              <div className="artifactRow" key={artifact.id}>
                <div>
                  <input
                    className="artifactTitleInput"
                    value={(artifactDrafts[artifact.id]?.title ?? artifact.title)}
                    onChange={(e) => {
                      const value = e.currentTarget.value;
                      setArtifactDrafts((prev) => ({
                        ...prev,
                        [artifact.id]: { title: value, content: prev[artifact.id]?.content ?? artifact.content },
                      }));
                    }}
                  />
                  <span>{artifact.type} · {artifact.created_at || ''}{artifact.is_final ? ' · final' : ''}</span>
                </div>
                <textarea
                  className="artifactEditor"
                  value={(artifactDrafts[artifact.id]?.content ?? artifact.content)}
                  onChange={(e) => {
                    const value = e.currentTarget.value;
                    setArtifactDrafts((prev) => ({
                      ...prev,
                      [artifact.id]: { title: prev[artifact.id]?.title ?? artifact.title, content: value },
                    }));
                  }}
                />
                <div className="sourceActions">
                  <button className="btn primary" type="button" onClick={() => saveArtifact(artifact)} disabled={loading}>
                    Save
                  </button>
                  <button className="btn secondary" type="button" onClick={() => markArtifactFinal(artifact)} disabled={loading}>
                    {artifact.is_final ? 'Unmark Final' : 'Mark Final'}
                  </button>
                  {artifact.type === 'code' ? (
                    <>
                      <button className="btn secondary" type="button" onClick={() => checkArtifact(artifact)} disabled={loading}>
                        Check
                      </button>
                      <button className="btn secondary" type="button" onClick={() => repairArtifact(artifact)} disabled={loading}>
                        Repair
                      </button>
                      <button className="btn secondary" type="button" onClick={() => runArtifact(artifact)} disabled={loading}>
                        Run
                      </button>
                    </>
                  ) : null}
                  <button className="btn secondary" type="button" onClick={() => loadArtifactVersions(artifact)} disabled={loading}>
                    Versions
                  </button>
                  <button className="btn secondary" type="button" onClick={() => copyArtifact(artifact)} disabled={!artifact.content}>
                    Copy
                  </button>
                  <button className="btn secondary" type="button" onClick={() => downloadArtifact(artifact)} disabled={!artifact.content}>
                    Download
                  </button>
                  <button className="btn danger" type="button" onClick={() => deleteArtifact(artifact)} disabled={loading}>
                    Delete
                  </button>
                </div>
                {artifactRuns[artifact.id] ? (
                  <div className={artifactRuns[artifact.id].success ? 'runOutput success' : 'runOutput error'}>
                    <strong>{artifactRuns[artifact.id].success ? 'Run passed' : 'Run failed'}</strong>
                    <span>Exit code: {String(artifactRuns[artifact.id].returncode ?? 'timeout')}</span>
                    {artifactRuns[artifact.id].stdout ? <pre>{artifactRuns[artifact.id].stdout}</pre> : null}
                    {artifactRuns[artifact.id].stderr ? <pre>{artifactRuns[artifact.id].stderr}</pre> : null}
                  </div>
                ) : null}
                {artifactVersions[artifact.id]?.length ? (
                  <div className="versionList">
                    {artifactVersions[artifact.id].map((version: any) => (
                      <details key={version.id}>
                        <summary>{version.created_at || 'Saved version'} {version.note ? `· ${version.note}` : ''}</summary>
                        <pre>{version.content}</pre>
                      </details>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
            {!project.artifacts?.length ? <div className="emptyState">Generated documents will appear here.</div> : null}
          </div>
        </div>
        ) : null}

        {sideTab === 'continuity' ? (
        <div className="panel">
          <div className="panelHeader">
            <h2>Continuity</h2>
          </div>
          <div className="continuityPanel">
            <div className="sourceRow">
              <strong>Current goal</strong>
              <span>{conversationState?.current_goal || 'No goal inferred yet.'}</span>
            </div>
            <div className="sourceRow">
              <strong>Latest file</strong>
              <span>{conversationState?.latest_file_name || 'No file referenced yet.'}</span>
            </div>
            <div className="sourceRow">
              <strong>Latest artifact</strong>
              <span>{conversationState?.latest_artifact_title || 'No artifact generated yet.'}</span>
            </div>
            <div className="sourceRow">
              <strong>Latest action</strong>
              <span>{conversationState?.latest_action || 'No action yet.'}</span>
            </div>
            <div className="sourceRow">
              <strong>User preferences</strong>
              {(conversationState?.user_preferences || []).map((item) => <span key={item}>{item}</span>)}
              {!conversationState?.user_preferences?.length ? <span>No preferences inferred yet.</span> : null}
            </div>
            <div className="sourceRow">
              <strong>Open tasks</strong>
              {(conversationState?.open_tasks || []).map((item) => <span key={item}>{item}</span>)}
              {!conversationState?.open_tasks?.length ? <span>No open tasks inferred yet.</span> : null}
            </div>
            <div className="sourceRow">
              <strong>Summary</strong>
              <p>{conversationState?.summary || 'Conversation summary will appear after project chat.'}</p>
            </div>
          </div>
        </div>
        ) : null}
      </aside>
    </section>
  );
}
