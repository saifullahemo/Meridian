import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ConversationMode from './ConversationMode';
import ProjectWorkspace from './ProjectWorkspace';

export type ChatMessage = {
  role: 'user' | 'assistant' | 'system';
  content: string;
  success?: boolean;
  action?: string;
  artifacts?: any[];
  sources?: any[];
  suggestions?: string[];
  route?: {
    action?: string;
    module?: string | null;
    explanation?: string;
  };
};

type Mode = 'dashboard' | 'resume' | 'jobs' | 'chat' | 'data' | 'rag' | 'memory' | 'observability';

type Field = {
  name: string;
  type: 'text' | 'number' | 'date' | 'enum' | 'boolean';
  required?: boolean;
  options?: string[];
};

type ModuleSchema = {
  label: string;
  icon?: string;
  description?: string;
  fields: Field[];
};

type ModulesMap = Record<string, ModuleSchema>;
type RecordRow = Record<string, string | number | boolean | null>;
type ProjectSummary = {
  id: number;
  name: string;
  description?: string;
  instructions?: string;
  file_count?: number;
  artifact_count?: number;
};
type ModuleDraft = {
  key: string;
  label: string;
  description: string;
  icon: string;
  fields: Field[];
};

const modeLabels: Record<Mode, string> = {
  dashboard: 'Home',
  resume: 'Files',
  jobs: 'Jobs',
  chat: 'Chat',
  data: 'Projects',
  rag: 'Knowledge',
  memory: 'Memory',
  observability: 'Logs',
};

const primaryModes: Mode[] = ['chat', 'data'];
const toolModes: Mode[] = ['dashboard', 'rag', 'resume', 'memory', 'jobs', 'observability'];

function todaySessionId() {
  return 'session_' + new Date().toISOString().slice(0, 10).replace(/-/g, '');
}

function formatLabel(value: string) {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

async function readJson<T>(res: Response): Promise<T> {
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(String((json as any).detail || (json as any).message || `Request failed (${res.status})`));
  }
  return json as T;
}

export default function App() {
  const [mode, setMode] = useState<Mode>('chat');
  const [sessionId, setSessionId] = useState<string>(() => {
    return localStorage.getItem('po_session_id') || todaySessionId();
  });
  const [modules, setModules] = useState<ModulesMap>({});
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [activeModule, setActiveModule] = useState('');
  const [activeProjectId, setActiveProjectId] = useState<number | null>(null);
  const [statusText, setStatusText] = useState('Checking');
  const [notice, setNotice] = useState<string | null>(null);

  const apiBase = useMemo(() => {
    return import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
  }, []);

  const api = useCallback((path: string) => apiBase.replace(/\/$/, '') + path, [apiBase]);

  const refreshModules = useCallback(async () => {
    const json = await readJson<{ modules: ModulesMap; counts: Record<string, number> }>(
      await fetch(api('/api/modules')),
    );
    setModules(json.modules || {});
    setCounts(json.counts || {});
    // Important: do not auto-select the first module when entering Projects/data mode.
    // Only keep the current selection if it exists.
    setActiveModule((current) => (current ? current : ''));
  }, [api]);

  const refreshProjects = useCallback(async () => {
    const json = await readJson<{ projects: ProjectSummary[] }>(
      await fetch(api('/api/projects')),
    );
    setProjects(Array.isArray(json.projects) ? json.projects : []);
  }, [api]);

  useEffect(() => {
    localStorage.setItem('po_session_id', sessionId);
  }, [sessionId]);

  useEffect(() => {
    refreshModules().catch((e) => setNotice(e.message));
    refreshProjects().catch((e) => setNotice(e.message));
    fetch(api('/api/status'))
      .then((res) => readJson<{ ai?: { ready?: boolean; model?: string; error?: string } }>(res))
      .then((json) => {
        if (json.ai?.ready) setStatusText(`AI online${json.ai.model ? `: ${json.ai.model}` : ''}`);
        else setStatusText(json.ai?.error || 'AI offline');
      })
      .catch((e) => setStatusText(e.message));
  }, [api, refreshModules, refreshProjects]);

  const activeProject = projects.find((project) => project.id === activeProjectId);
  const pageTitle = mode === 'data' && activeProject ? activeProject.name : modeLabels[mode];

  return (
    <div className="appShell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark">PO</div>
          <div>
            <div className="title">Personal OS</div>
            <div className="subtitle">Local AI workspace</div>
          </div>
        </div>

        <nav className="nav" aria-label="Main navigation">
          <div className="railLabel">Main</div>
          {primaryModes.map((item) => (
            <button
              key={item}
              className={mode === item ? 'navButton active' : 'navButton'}
              type="button"
              onClick={() => setMode(item)}
            >
              {modeLabels[item]}
            </button>
          ))}
          <div className="railLabel navGroupLabel">Tools</div>
          {toolModes.map((item) => (
            <button
              key={item}
              className={mode === item ? 'navButton active' : 'navButton'}
              type="button"
              onClick={() => setMode(item)}
            >
              {modeLabels[item]}
            </button>
          ))}
        </nav>

        <div className="moduleRail">
          <div className="railLabel">Projects</div>
          {projects.map((project) => (
            <button
              key={project.id}
              className={activeProjectId === project.id && mode === 'data' ? 'moduleButton active' : 'moduleButton'}
              type="button"
              onClick={() => {
                setActiveProjectId(project.id);
                setMode('data');
              }}
            >
              <span>{project.name}</span>
              <strong>{project.file_count || 0}</strong>
            </button>
          ))}
          <button
            className={mode === 'data' && !activeProjectId ? 'moduleButton active' : 'moduleButton'}
            type="button"
            onClick={() => {
              setActiveProjectId(null);
              setMode('data');
            }}
          >
            <span>+ New project</span>
            <strong>+</strong>
          </button>
        </div>

        <div className={statusText.startsWith('AI online') ? 'statusPill online' : 'statusPill'}>
          <span>{statusText.startsWith('AI online') ? 'Online' : 'Check'}</span>
          <strong>{statusText.replace(/^AI online:?\s*/, '')}</strong>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <div className="eyebrow">{modeLabels[mode]}</div>
            <h1>{pageTitle}</h1>
          </div>
          <label className="sessionControl">
            <span>Session</span>
            <input value={sessionId} onChange={(e) => setSessionId(e.currentTarget.value)} />
          </label>
        </header>

        {notice ? <div className="notice">{notice}</div> : null}

        {mode === 'dashboard' ? (
          <DashboardView api={api} setMode={setMode} setActiveModule={setActiveModule} />
        ) : null}
        {mode === 'resume' ? <ResumeView api={api} /> : null}
        {mode === 'jobs' ? <JobsView api={api} sessionId={sessionId} /> : null}
        {mode === 'chat' ? (
          <ConversationMode
            apiBaseUrl={apiBase}
            sessionId={sessionId}
            setSessionId={setSessionId}
            onProjectsChanged={refreshProjects}
          />
        ) : null}
        {mode === 'data' ? (
          <ProjectWorkspace
            api={api}
            projects={projects}
            activeProjectId={activeProjectId}
            setActiveProjectId={setActiveProjectId}
            onChanged={refreshProjects}
          />
        ) : null}
        {mode === 'rag' ? <RagView api={api} /> : null}
        {mode === 'memory' ? <MemoryView api={api} sessionId={sessionId} /> : null}
        {mode === 'observability' ? <ObservabilityView api={api} sessionId={sessionId} /> : null}
      </main>
    </div>
  );
}

function DataView({
  api,
  modules,
  moduleKey,
  setActiveModule,
  onChanged,
}: {
  api: (path: string) => string;
  modules: ModulesMap;
  moduleKey: string;
  setActiveModule: (moduleKey: string) => void;
  onChanged: () => Promise<void>;
}) {
  const schema = modules[moduleKey];
  const [records, setRecords] = useState<RecordRow[]>([]);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('All');
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<Record<string, string | number | boolean>>({});
  const [editingId, setEditingId] = useState<string | number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showModuleEditor, setShowModuleEditor] = useState(false);
  const [moduleEditorMode, setModuleEditorMode] = useState<'create' | 'edit'>('create');
  const [moduleDraft, setModuleDraft] = useState({
    key: '',
    label: '',
    description: '',
    icon: '',
    fields: defaultFields(),
  });

  const loadRecords = useCallback(async () => {
    if (!moduleKey) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      if (status !== 'All') params.set('status', status);
      const json = await readJson<{ records: RecordRow[] }>(
        await fetch(api(`/api/modules/${moduleKey}/records?${params.toString()}`)),
      );
      setRecords(json.records || []);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [api, moduleKey, search, status]);

  useEffect(() => {
    setForm({});
    setEditingId(null);
    setShowForm(false);
  }, [moduleKey]);

  useEffect(() => {
    loadRecords();
  }, [loadRecords]);

  async function saveModule() {
    setError(null);
    try {
      const isEdit = moduleEditorMode === 'edit' && Boolean(schema);
      const key = isEdit ? moduleKey : moduleDraft.key;
      const schemaPayload = schemaFromDraft(moduleDraft, schema);
      await readJson(
        await fetch(api(isEdit ? `/api/modules/${moduleKey}` : '/api/modules'), {
          method: isEdit ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key, schema: schemaPayload }),
        }),
      );
      setShowModuleEditor(false);
      await onChanged();
      setActiveModule(key);
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  async function deleteModule() {
    if (!schema || !moduleKey) return;
    if (!window.confirm(`Delete ${schema.label || moduleKey} and its saved records?`)) return;
    setError(null);
    try {
      await readJson(await fetch(api(`/api/modules/${moduleKey}?drop_data=true`), { method: 'DELETE' }));
      setActiveModule('');
      await onChanged();
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  function openModuleEditor(createNew = false) {
    if (createNew || !schema) {
      setModuleEditorMode('create');
      setModuleDraft({
        key: '',
        label: '',
        description: '',
        icon: '',
        fields: defaultFields(),
      });
    } else {
      setModuleEditorMode('edit');
      setModuleDraft({
        key: moduleKey,
        label: schema.label || moduleKey,
        description: schema.description || '',
        icon: schema.icon || '',
        fields: schema.fields.map((field) => ({ ...field, options: field.options ? [...field.options] : undefined })),
      });
    }
    setShowModuleEditor(true);
  }

  function updateDraftField(index: number, patch: Partial<Field>) {
    setModuleDraft((prev) => ({
      ...prev,
      fields: prev.fields.map((field, i) => i === index ? { ...field, ...patch } : field),
    }));
  }

  function addDraftField() {
    setModuleDraft((prev) => ({
      ...prev,
      fields: [...prev.fields, { name: '', type: 'text', required: false }],
    }));
  }

  function removeDraftField(index: number) {
    setModuleDraft((prev) => ({
      ...prev,
      fields: prev.fields.filter((_, i) => i !== index),
    }));
  }

  if (!schema && !showModuleEditor) {
    return (
      <section className="dataLayout">
        {error ? <div className="notice error">{error}</div> : null}
        <div className="emptyState">No tracker selected. Create anything you want to track.</div>
        <button className="btn primary" type="button" onClick={() => openModuleEditor(true)}>Create Tracker</button>
      </section>
    );
  }

  if (!schema) {
    return (
      <section className="dataLayout">
        {error ? <div className="notice error">{error}</div> : null}
        <div className="panel moduleEditor">
          <div className="panelHeader">
            <h2>Create Tracker</h2>
          </div>
          <div className="formPanel">
            <label className="field">
              <span>Key</span>
              <input value={moduleDraft.key} onChange={(e) => {
                const value = e.currentTarget.value;
                setModuleDraft((prev) => ({ ...prev, key: value }));
              }} placeholder="travel_plans" />
            </label>
            <label className="field">
              <span>Label</span>
              <input value={moduleDraft.label} onChange={(e) => {
                const value = e.currentTarget.value;
                setModuleDraft((prev) => ({ ...prev, label: value }));
              }} placeholder="Travel Plans" />
            </label>
            <label className="field">
              <span>Icon</span>
              <input value={moduleDraft.icon} onChange={(e) => {
                const value = e.currentTarget.value;
                setModuleDraft((prev) => ({ ...prev, icon: value }));
              }} placeholder="*" />
            </label>
            <label className="field">
              <span>Description</span>
              <input value={moduleDraft.description} onChange={(e) => {
                const value = e.currentTarget.value;
                setModuleDraft((prev) => ({ ...prev, description: value }));
              }} placeholder="Track anything you want" />
            </label>
            <ModuleFieldBuilder fields={moduleDraft.fields} onAdd={addDraftField} onRemove={removeDraftField} onChange={updateDraftField} />
            <div className="formActions">
              <button className="btn secondary" type="button" onClick={() => setShowModuleEditor(false)}>Cancel</button>
              <button className="btn primary" type="button" onClick={saveModule}>Create Tracker</button>
            </div>
          </div>
        </div>
      </section>
    );
  }

  const statusField = schema.fields.find((field) => field.name === 'status' && field.options?.length);
  const columns = orderColumns(records);

  async function saveRecord() {
    setError(null);
    try {
      const path = editingId
        ? `/api/modules/${moduleKey}/records/${editingId}`
        : `/api/modules/${moduleKey}/records`;
      await readJson(
        await fetch(api(path), {
          method: editingId ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ data: form }),
        }),
      );
      setShowForm(false);
      setForm({});
      setEditingId(null);
      await loadRecords();
      await onChanged();
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  async function deleteRecord(id: unknown) {
    if (!id) return;
    setError(null);
    try {
      await readJson(await fetch(api(`/api/modules/${moduleKey}/records/${id}`), { method: 'DELETE' }));
      await loadRecords();
      await onChanged();
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }

  return (
    <section className="dataLayout">
      <div className="toolbar">
        <input value={search} onChange={(e) => setSearch(e.currentTarget.value)} placeholder="Search records" />
        {statusField ? (
          <select value={status} onChange={(e) => setStatus(e.currentTarget.value)}>
            <option>All</option>
            {statusField.options?.map((option) => <option key={option}>{option}</option>)}
          </select>
        ) : null}
        <button className="btn primary" type="button" onClick={() => setShowForm((value) => !value)}>
          {showForm ? 'Close' : 'Add'}
        </button>
        <button className="btn secondary" type="button" onClick={() => openModuleEditor(false)}>Edit Tracker</button>
        <button className="btn secondary" type="button" onClick={() => openModuleEditor(true)}>New Tracker</button>
      </div>

      <div className="metricGrid">
        <Metric label="Showing" value={records.length} />
        <Metric label="Fields" value={schema.fields.length} />
        <Metric label="Latest" value={String(records[0]?.created_at || '-').slice(0, 10)} />
      </div>

      {error ? <div className="notice error">{error}</div> : null}

      {showModuleEditor ? (
        <div className="panel moduleEditor">
          <div className="panelHeader">
            <h2>{moduleEditorMode === 'edit' ? 'Edit Tracker' : 'Create Tracker'}</h2>
            {moduleEditorMode === 'edit' ? <button className="btn secondary" type="button" onClick={deleteModule}>Delete Tracker</button> : null}
          </div>
          <div className="formPanel">
            <label className="field">
              <span>Key</span>
              <input value={moduleDraft.key} disabled={moduleEditorMode === 'edit'} onChange={(e) => {
                const value = e.currentTarget.value;
                setModuleDraft((prev) => ({ ...prev, key: value }));
              }} placeholder="travel_plans" />
            </label>
            <label className="field">
              <span>Label</span>
              <input value={moduleDraft.label} onChange={(e) => {
                const value = e.currentTarget.value;
                setModuleDraft((prev) => ({ ...prev, label: value }));
              }} placeholder="Travel Plans" />
            </label>
            <label className="field">
              <span>Icon</span>
              <input value={moduleDraft.icon} onChange={(e) => {
                const value = e.currentTarget.value;
                setModuleDraft((prev) => ({ ...prev, icon: value }));
              }} placeholder="*" />
            </label>
            <label className="field">
              <span>Description</span>
              <input value={moduleDraft.description} onChange={(e) => {
                const value = e.currentTarget.value;
                setModuleDraft((prev) => ({ ...prev, description: value }));
              }} placeholder="Track anything you want" />
            </label>
            <ModuleFieldBuilder fields={moduleDraft.fields} onAdd={addDraftField} onRemove={removeDraftField} onChange={updateDraftField} />
            <div className="formActions">
              <button className="btn secondary" type="button" onClick={() => setShowModuleEditor(false)}>Cancel</button>
              <button className="btn primary" type="button" onClick={saveModule}>{moduleEditorMode === 'edit' ? 'Update Tracker' : 'Create Tracker'}</button>
            </div>
          </div>
        </div>
      ) : null}

      {showForm ? (
        <div className="panel formPanel">
          {schema.fields.map((field) => (
            <label className="field" key={field.name}>
              <span>{formatLabel(field.name)}{field.required ? ' *' : ''}</span>
              <FieldInput field={field} value={form[field.name]} onChange={(value) => setForm((prev) => ({ ...prev, [field.name]: value }))} />
            </label>
          ))}
          <div className="formActions">
            <button className="btn secondary" type="button" onClick={() => {
              setShowForm(false);
              setEditingId(null);
              setForm({});
            }}>Cancel</button>
            <button className="btn primary" type="button" onClick={saveRecord}>{editingId ? 'Update' : 'Save'}</button>
          </div>
        </div>
      ) : null}

      <div className="panel tablePanel">
        {loading ? <div className="emptyState">Loading records...</div> : null}
        {!loading && records.length === 0 ? <div className="emptyState">No records found.</div> : null}
        {records.length ? (
          <table>
            <thead>
              <tr>
                {columns.map((column) => <th key={column}>{formatLabel(column)}</th>)}
                <th />
              </tr>
            </thead>
            <tbody>
              {records.map((record, index) => (
                <tr key={String(record.id || index)}>
                  {columns.map((column) => <td key={column}>{String(record[column] ?? '')}</td>)}
                  <td className="rowActions">
                    <button
                      className="iconButton"
                      type="button"
                      title="Edit record"
                      onClick={() => {
                        setEditingId(record.id == null ? null : String(record.id));
                        setForm(recordToForm(record));
                        setShowForm(true);
                      }}
                    >
                      Edit
                    </button>
                    <button className="iconButton" type="button" title="Delete record" onClick={() => deleteRecord(record.id)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </section>
  );
}

function ResumeView({ api }: { api: (path: string) => string }) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function extract() {
    if (!file) return;
    setLoading(true);
    setError(null);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('save', 'true');
    try {
      const json = await readJson<any>(
        await fetch(api('/api/files/extract'), {
          method: 'POST',
          body: fd,
        }),
      );
      setResult(json);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  const skills = extractSkillHints(String(result?.text || ''));

  return (
    <section className="resumeGrid">
      <div className="panel resumePanel">
        <div className="panelHeader">
          <h2>Resume Parser</h2>
        </div>
        <div className="uploadBox">
          <input
            type="file"
            accept=".pdf,.docx,.txt,.md"
            onChange={(e) => setFile(e.currentTarget.files?.[0] || null)}
          />
          <button className="btn primary" type="button" onClick={extract} disabled={!file || loading}>
            {loading ? 'Reading...' : 'Extract Resume'}
          </button>
        </div>
        {error ? <div className="notice error">{error}</div> : null}
        {result ? (
          <div className={result.success ? 'notice success' : 'notice error'}>
            {result.filename}: {result.words} words, {result.chars} characters extracted
          </div>
        ) : null}
      </div>

      <div className="panel resumePanel">
        <div className="panelHeader">
          <h2>Detected Skills</h2>
        </div>
        <div className="chipList">
          {skills.map((skill) => <span className="fileChip" key={skill}>{skill}</span>)}
          {!skills.length ? <div className="emptyState">Upload a resume to detect common technical keywords.</div> : null}
        </div>
      </div>

      <div className="panel previewPanel">
        <div className="panelHeader">
          <h2>Extracted Text Preview</h2>
        </div>
        <pre>{result?.preview || 'No resume text extracted yet.'}</pre>
      </div>
    </section>
  );
}

function JobsView({ api, sessionId }: { api: (path: string) => string; sessionId: string }) {
  const [query, setQuery] = useState('QA Engineer');
  const [location, setLocation] = useState('Singapore');
  const [message, setMessage] = useState('');
  const [jobs, setJobs] = useState<RecordRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function searchJobs() {
    setLoading(true);
    setError(null);
    try {
      const json = await readJson<any>(
        await fetch(api('/api/jobs/search'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query, location, session_id: sessionId }),
        }),
      );
      setMessage(String(json.message || ''));
      setJobs(Array.isArray(json.data) ? json.data : []);
    } catch (e: any) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  const columns = orderColumns(jobs);

  return (
    <section className="dataLayout">
      <div className="toolbar">
        <input value={query} onChange={(e) => setQuery(e.currentTarget.value)} placeholder="Role, skill, or keyword" />
        <input value={location} onChange={(e) => setLocation(e.currentTarget.value)} placeholder="Location" />
        <button className="btn primary" type="button" onClick={searchJobs} disabled={loading || !query.trim()}>
          {loading ? 'Searching...' : 'Search Jobs'}
        </button>
      </div>
      {error ? <div className="notice error">{error}</div> : null}
      {message ? <div className="notice">{message}</div> : null}
      <div className="panel tablePanel">
        {!jobs.length ? <div className="emptyState">Search for jobs to see results here. Saved job search results can also flow into the Jobs data module.</div> : null}
        {jobs.length ? (
          <table>
            <thead>
              <tr>{columns.map((column) => <th key={column}>{formatLabel(column)}</th>)}</tr>
            </thead>
            <tbody>
              {jobs.map((job, index) => (
                <tr key={index}>{columns.map((column) => <td key={column}>{String(job[column] ?? '')}</td>)}</tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </section>
  );
}

function DashboardView({
  api,
  setMode,
  setActiveModule,
}: {
  api: (path: string) => string;
  setMode: (mode: Mode) => void;
  setActiveModule: (moduleKey: string) => void;
}) {
  const [items, setItems] = useState<Array<{ key: string; module: ModuleSchema; count: number; recent: RecordRow[] }>>([]);
  const [notifications, setNotifications] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(api('/api/dashboard'))
      .then((res) => readJson<{ items: Array<{ key: string; module: ModuleSchema; count: number; recent: RecordRow[] }>; notifications?: any[] }>(res))
      .then((json) => {
        setItems(json.items || []);
        setNotifications(json.notifications || []);
      })
      .catch((e) => setError(e.message));
  }, [api]);

  if (error) return <div className="notice error">{error}</div>;

  return (
    <section className="dashboard">
      <div className="metricGrid">
        {items.map((item) => (
          <button
            key={item.key}
            className="metricButton"
            type="button"
            onClick={() => {
              setActiveModule(item.key);
              setMode('data');
            }}
          >
            <span>{item.module.icon || '□'}</span>
            <strong>{item.count}</strong>
            <em>{item.module.label || item.key}</em>
          </button>
        ))}
      </div>

      <div className="proactiveBand">
        <div className="panelHeader">
          <h2>Proactive Intelligence</h2>
          <button
            className="btn secondary"
            type="button"
            onClick={() => {
              fetch(api('/api/proactive/run'), { method: 'POST' })
                .then(() => fetch(api('/api/dashboard')))
                .then((res) => readJson<{ notifications?: any[]; items: any[] }>(res))
                .then((json) => {
                  setNotifications(json.notifications || []);
                  setItems(json.items || []);
                })
                .catch((e) => setError(e.message));
            }}
          >
            Scan Now
          </button>
        </div>
        <div className="notificationGrid">
          {notifications.map((item) => (
            <div className={`notificationCard ${item.severity || 'info'}`} key={item.id}>
              <strong>{item.title}</strong>
              <p>{item.message}</p>
              <span>{item.module || 'system'} · {item.suggested_action || 'Review'}</span>
            </div>
          ))}
          {!notifications.length ? <div className="emptyState">No proactive alerts yet. Run a scan after adding data.</div> : null}
        </div>
      </div>

      <div className="recentGrid">
        {items.filter((item) => item.recent.length).map((item) => (
          <div className="panel recentPanel" key={item.key}>
            <div className="panelHeader">
              <h2>{item.module.icon || '□'} {item.module.label}</h2>
              <button
                className="btn secondary"
                type="button"
                onClick={() => {
                  setActiveModule(item.key);
                  setMode('data');
                }}
              >
                View
              </button>
            </div>
            {item.recent.slice(0, 5).map((record, index) => (
              <div className="recentRow" key={String(record.id || index)}>
                <strong>{record.company || record.title || record.category || record.type || `Record ${record.id || index + 1}`}</strong>
                <span>{String(record.status || record.date || record.date_applied || record.created_at || '').slice(0, 32)}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

function MemoryView({ api, sessionId }: { api: (path: string) => string; sessionId: string }) {
  const [history, setHistory] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [summary, setSummary] = useState('');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedSession, setSelectedSession] = useState(sessionId);

  const loadHistory = useCallback(async () => {
    const json = await readJson<{ history: any[]; summary: string }>(await fetch(api(`/api/memory/${selectedSession}`)));
    setHistory(json.history || []);
    setSummary(json.summary || '');
  }, [api, selectedSession]);

  useEffect(() => {
    setSelectedSession(sessionId);
  }, [sessionId]);

  useEffect(() => {
    fetch(api('/api/memory/sessions/list'))
      .then((res) => readJson<{ sessions: any[] }>(res))
      .then((json) => setSessions(json.sessions || []))
      .catch(() => undefined);
    loadHistory().catch(() => undefined);
  }, [api, loadHistory]);

  async function searchMemory() {
    if (!query.trim()) return;
    const json = await readJson<{ results: any[] }>(
      await fetch(api('/api/memory/search'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      }),
    );
    setResults(json.results || []);
  }

  async function summarize() {
    setLoading(true);
    try {
      const json = await readJson<{ summary: string }>(await fetch(api(`/api/memory/${selectedSession}/summarize`), { method: 'POST' }));
      setSummary(json.summary || '');
    } finally {
      setLoading(false);
    }
  }

  async function clear() {
    await readJson(await fetch(api(`/api/memory/${selectedSession}`), { method: 'DELETE' }));
    setHistory([]);
    setSummary('');
  }

  return (
    <section className="memoryGrid">
      <div className="panel">
        <div className="panelHeader">
          <h2>Session Memory</h2>
          <div className="actions">
            <button className="btn secondary" type="button" onClick={summarize} disabled={loading}>Summarize</button>
            <button className="btn secondary" type="button" onClick={clear}>Clear</button>
          </div>
        </div>
        {summary ? <p className="summary">{summary}</p> : null}
        <select value={selectedSession} onChange={(e) => setSelectedSession(e.currentTarget.value)}>
          <option value={sessionId}>{sessionId}</option>
          {sessions.map((session) => (
            <option key={session.session_id} value={session.session_id}>
              {session.session_id} ({session.message_count})
            </option>
          ))}
        </select>
        <div className="memoryList">
          {history.map((item, index) => (
            <div className="memoryItem" key={index}>
              <span>{item.role}</span>
              <p>{item.content}</p>
            </div>
          ))}
          {!history.length ? <div className="emptyState">No memory saved for this session yet.</div> : null}
        </div>
      </div>

      <div className="panel">
        <div className="panelHeader">
          <h2>Search Memory</h2>
        </div>
        <div className="toolbar single">
          <input value={query} onChange={(e) => setQuery(e.currentTarget.value)} placeholder="Search past conversations" />
          <button className="btn primary" type="button" onClick={searchMemory}>Search</button>
        </div>
        <div className="memoryList">
          {results.map((item, index) => (
            <div className="memoryItem" key={index}>
              <span>{item.session_id} · {item.role}</span>
              <p>{item.content}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function RagView({ api }: { api: (path: string) => string }) {
  const [source, setSource] = useState('notes');
  const [text, setText] = useState('');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [query, setQuery] = useState('');
  const [answerMode, setAnswerMode] = useState(true);
  const [answer, setAnswer] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [sources, setSources] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const loadSources = useCallback(async () => {
    const json = await readJson<{ sources: any[] }>(await fetch(api('/api/rag/sources')));
    setSources(json.sources || []);
  }, [api]);

  useEffect(() => {
    loadSources().catch(() => undefined);
  }, [loadSources]);

  async function ingestText() {
    if (!source.trim() || !text.trim()) return;
    setLoading(true);
    setNotice(null);
    try {
      const json = await readJson<any>(
        await fetch(api('/api/rag/ingest'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source, text }),
        }),
      );
      setNotice(`Indexed ${json.chunks} chunks from ${json.source}`);
      setText('');
      await loadSources();
    } catch (e: any) {
      setNotice(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function ingestFile() {
    if (!file) return;
    setLoading(true);
    setNotice(null);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const json = await readJson<any>(await fetch(api('/api/rag/ingest-file'), { method: 'POST', body: fd }));
      setNotice(`Indexed ${json.chunks} chunks from ${json.source}`);
      setFile(null);
      await loadSources();
    } catch (e: any) {
      setNotice(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function ingestUrl() {
    if (!url.trim()) return;
    setLoading(true);
    setNotice(null);
    try {
      const json = await readJson<any>(
        await fetch(api('/api/rag/ingest-url'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ source: url }),
        }),
      );
      setNotice(`Indexed ${json.chunks} chunks from ${json.title || json.source}`);
      await loadSources();
    } catch (e: any) {
      setNotice(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  async function runQuery() {
    if (!query.trim()) return;
    setLoading(true);
    setNotice(null);
    setAnswer('');
    try {
      const json = await readJson<any>(
        await fetch(api('/api/rag/query'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query, top_k: 5, answer: answerMode }),
        }),
      );
      setAnswer(String(json.message || ''));
      setResults(answerMode ? (json.sources || []) : (json.results || []));
    } catch (e: any) {
      setNotice(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="ragGrid">
      <div className="panel ragPanel">
        <div className="panelHeader">
          <h2>Sources</h2>
        </div>
        <div className="ragSourceList">
          {sources.map((item, index) => (
            <div className="sourceRow" key={index}>
              <strong>{item.title || item.source}</strong>
              <span>{item.source_type} · {item.chunks} chunks</span>
            </div>
          ))}
          {!sources.length ? <div className="emptyState">No indexed sources yet.</div> : null}
        </div>
      </div>

      <div className="panel ragPanel">
        <div className="panelHeader">
          <h2>Ingest</h2>
        </div>
        <label className="field">
          <span>Source</span>
          <input value={source} onChange={(e) => setSource(e.currentTarget.value)} />
        </label>
        <textarea value={text} onChange={(e) => setText(e.currentTarget.value)} placeholder="Paste notes or document text" />
        <div className="actions">
          <button className="btn primary" type="button" onClick={ingestText} disabled={loading || !text.trim()}>
            Index Text
          </button>
        </div>
        <div className="splitControls">
          <input type="file" accept=".pdf,.docx,.txt,.md,.json,.csv" onChange={(e) => setFile(e.currentTarget.files?.[0] || null)} />
          <button className="btn secondary" type="button" onClick={ingestFile} disabled={loading || !file}>
            Index File
          </button>
        </div>
        <div className="splitControls">
          <input value={url} onChange={(e) => setUrl(e.currentTarget.value)} placeholder="https://example.com/page" />
          <button className="btn secondary" type="button" onClick={ingestUrl} disabled={loading || !url.trim()}>
            Index URL
          </button>
        </div>
        {notice ? <div className="notice">{notice}</div> : null}
      </div>

      <div className="panel ragPanel ragQuery">
        <div className="panelHeader">
          <h2>Query</h2>
          <label className="inlineToggle">
            <input type="checkbox" checked={answerMode} onChange={(e) => setAnswerMode(e.currentTarget.checked)} />
            <span>Answer</span>
          </label>
        </div>
        <textarea value={query} onChange={(e) => setQuery(e.currentTarget.value)} placeholder="Ask about indexed sources" />
        <div className="actions">
          <button className="btn primary" type="button" onClick={runQuery} disabled={loading || !query.trim()}>
            {loading ? 'Working...' : 'Run Query'}
          </button>
        </div>
        {answer ? <div className="ragAnswer">{answer}</div> : null}
        <div className="ragResults">
          {results.map((item, index) => (
            <div className="resultRow" key={index}>
              <strong>{item.citation || `${item.title || item.source}#${item.chunk_id ?? ''}`}</strong>
              <span>score {item.score ?? '-'}</span>
              {item.text ? <p>{item.text}</p> : null}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function ObservabilityView({ api, sessionId }: { api: (path: string) => string; sessionId: string }) {
  const [events, setEvents] = useState<any[]>([]);
  const [summary, setSummary] = useState<any | null>(null);
  const [filterSession, setFilterSession] = useState(false);
  const [eventFilter, setEventFilter] = useState('');
  const [projectFilter, setProjectFilter] = useState('');
  const [error, setError] = useState<string | null>(null);

  const loadEvents = useCallback(async () => {
    setError(null);
    try {
      const params = new URLSearchParams({ limit: '100' });
      if (filterSession) params.set('session_id', sessionId);
      if (eventFilter.trim()) params.set('event', eventFilter.trim());
      if (projectFilter.trim()) params.set('project_id', projectFilter.trim());
      const json = await readJson<{ events: any[] }>(await fetch(api(`/api/observability/events?${params}`)));
      setEvents(json.events || []);
      const summaryJson = await readJson<{ summary: any }>(await fetch(api('/api/observability/summary?limit=500')));
      setSummary(summaryJson.summary || null);
    } catch (e: any) {
      setError(String(e.message || e));
    }
  }, [api, eventFilter, filterSession, projectFilter, sessionId]);

  useEffect(() => {
    loadEvents();
  }, [loadEvents]);

  return (
    <section className="dataLayout">
      <div className="toolbar">
        <label className="inlineToggle">
          <input type="checkbox" checked={filterSession} onChange={(e) => setFilterSession(e.currentTarget.checked)} />
          <span>Current session</span>
        </label>
        <input value={eventFilter} onChange={(e) => setEventFilter(e.currentTarget.value)} placeholder="Filter event" />
        <input value={projectFilter} onChange={(e) => setProjectFilter(e.currentTarget.value)} placeholder="Project id" />
        <button className="btn primary" type="button" onClick={loadEvents}>Refresh</button>
      </div>
      {error ? <div className="notice error">{error}</div> : null}
      {summary ? (
        <div className="metricGrid">
          <Metric label="Trace events" value={summary.total ?? 0} />
          <Metric label="Errors" value={summary.errors ?? 0} />
          <Metric label="Avg latency" value={summary.avg_latency_ms ? `${summary.avg_latency_ms} ms` : '-'} />
        </div>
      ) : null}
      {summary ? (
        <div className="observabilitySummary">
          <div className="panel">
            <div className="panelHeader"><h2>Top Events</h2></div>
            {Object.entries(summary.by_event || {}).map(([name, count]) => (
              <button className="eventChip" type="button" key={name} onClick={() => setEventFilter(name)}>
                <span>{name}</span>
                <strong>{String(count)}</strong>
              </button>
            ))}
          </div>
          <div className="panel">
            <div className="panelHeader"><h2>Loggers</h2></div>
            {Object.entries(summary.by_logger || {}).map(([name, count]) => (
              <div className="eventChip" key={name}>
                <span>{name}</span>
                <strong>{String(count)}</strong>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <div className="panel tablePanel">
        {!events.length ? <div className="emptyState">No trace events found.</div> : null}
        {events.length ? (
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Event</th>
                <th>Logger</th>
	                <th>Request</th>
	                <th>Session</th>
	                <th>Project</th>
	                <th>Data</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
                  <td>{event.created_at}</td>
                  <td>{event.event}</td>
                  <td>{event.logger}</td>
	                  <td>{event.request_id}</td>
	                  <td>{event.session_id}</td>
	                  <td>{event.project_id}</td>
	                  <td><pre className="traceData">{JSON.stringify(event.data, null, 2)}</pre></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </section>
  );
}

function FieldInput({
  field,
  value,
  onChange,
}: {
  field: Field;
  value: string | number | boolean | undefined;
  onChange: (value: string | number | boolean) => void;
}) {
  if (field.type === 'enum' && field.options) {
    return (
      <select value={String(value ?? '')} onChange={(e) => onChange(e.currentTarget.value)}>
        <option value="">Select...</option>
        {field.options.map((option) => <option key={option}>{option}</option>)}
      </select>
    );
  }
  if (field.type === 'boolean') {
    return <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.currentTarget.checked)} />;
  }
  return (
    <input
      type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'}
      value={String(value ?? '')}
      onChange={(e) => onChange(field.type === 'number' ? Number(e.currentTarget.value) : e.currentTarget.value)}
    />
  );
}

function ModuleFieldBuilder({
  fields,
  onAdd,
  onRemove,
  onChange,
}: {
  fields: Field[];
  onAdd: () => void;
  onRemove: (index: number) => void;
  onChange: (index: number, patch: Partial<Field>) => void;
}) {
  return (
    <div className="fieldBuilder">
      <div className="fieldBuilderHeader">
        <span>Fields</span>
        <button className="btn secondary" type="button" onClick={onAdd}>Add Field</button>
      </div>
      {fields.map((field, index) => (
        <div className="fieldRow" key={index}>
          <input
            value={field.name}
            onChange={(e) => onChange(index, { name: e.currentTarget.value })}
            placeholder="field_name"
          />
          <select
            value={field.type}
            onChange={(e) => {
              const type = e.currentTarget.value as Field['type'];
              onChange(index, { type, options: type === 'enum' ? field.options || ['planned', 'done'] : undefined });
            }}
          >
            <option value="text">Text</option>
            <option value="number">Number</option>
            <option value="date">Date</option>
            <option value="enum">Options</option>
            <option value="boolean">Yes/No</option>
          </select>
          <label className="inlineToggle">
            <input
              type="checkbox"
              checked={Boolean(field.required)}
              onChange={(e) => onChange(index, { required: e.currentTarget.checked })}
            />
            <span>Required</span>
          </label>
          {field.type === 'enum' ? (
            <input
              value={(field.options || []).join(', ')}
              onChange={(e) => onChange(index, { options: e.currentTarget.value.split(',').map((item) => item.trim()).filter(Boolean) })}
              placeholder="planned, done"
            />
          ) : null}
          <button className="iconButton" type="button" onClick={() => onRemove(index)} disabled={fields.length <= 1}>Remove</button>
        </div>
      ))}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function orderColumns(records: RecordRow[]) {
  const columns = Array.from(new Set(records.flatMap((record) => Object.keys(record))));
  const priority = ['id', 'company', 'position', 'country', 'status', 'date_applied', 'date', 'title', 'type', 'amount', 'category', 'notes'];
  return [
    ...priority.filter((column) => columns.includes(column)),
    ...columns.filter((column) => !priority.includes(column) && !['created_at', 'updated_at'].includes(column)),
  ];
}

function recordToForm(record: RecordRow) {
  const next: Record<string, string | number | boolean> = {};
  for (const [key, value] of Object.entries(record)) {
    if (['id', 'created_at', 'updated_at'].includes(key)) continue;
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      next[key] = value;
    }
  }
  return next;
}

function schemaFromDraft(draft: ModuleDraft, existing?: ModuleSchema) {
  return {
    label: draft.label.trim() || existing?.label || 'Untitled Module',
    icon: draft.icon.trim(),
    description: draft.description.trim() || existing?.description || 'Custom module',
    fields: draft.fields
      .map((field) => {
        const type = ['text', 'number', 'date', 'enum', 'boolean'].includes(field.type) ? field.type : 'text';
        const next: Field = {
          name: field.name.trim().toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, ''),
          type,
          required: Boolean(field.required),
        };
        if (type === 'enum') {
          next.options = (field.options || []).map((item) => item.trim()).filter(Boolean);
          if (!next.options.length) next.options = ['planned', 'done'];
        }
        return next;
      })
      .filter((field) => field.name),
    sources: ['manual'],
  };
}

function defaultFields(): Field[] {
  return [
    { name: 'title', type: 'text', required: true },
    { name: 'status', type: 'enum', required: true, options: ['planned', 'in_progress', 'done'] },
    { name: 'notes', type: 'text', required: false },
  ];
}

function extractSkillHints(text: string) {
  const skills = [
    'Python', 'JavaScript', 'TypeScript', 'React', 'FastAPI', 'SQL', 'Excel',
    'QA', 'Automation', 'Selenium', 'Playwright', 'API Testing', 'Docker',
    'AWS', 'Machine Learning', 'Data Analysis', 'Project Management',
  ];
  const lower = text.toLowerCase();
  return skills.filter((skill) => lower.includes(skill.toLowerCase()));
}
