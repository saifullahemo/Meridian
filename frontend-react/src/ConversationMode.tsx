import React, { useCallback, useMemo, useRef, useState } from 'react';
import type { ChatMessage } from './App';

function truncate(s: string, n: number) {
  if (s.length <= n) return s;
  return s.slice(0, n) + `\n\n[Truncated ${n} chars]`;
}

export default function ConversationMode({
  apiBaseUrl,
  sessionId,
  setSessionId,
}: {
  apiBaseUrl: string;
  sessionId: string;
  setSessionId: (sessionId: string) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [renamingSession, setRenamingSession] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [instruction, setInstruction] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const endRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const apiRoot = useMemo(() => apiBaseUrl.replace(/\/$/, ''), [apiBaseUrl]);

  const loadSessions = useCallback(async () => {
    const res = await fetch(apiRoot + '/api/memory/sessions/list');
    const json = await res.json();
    if (res.ok && json.success) setSessions(json.sessions || []);
  }, [apiRoot]);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setError(null);
    try {
      const res = await fetch(apiRoot + `/api/memory/${encodeURIComponent(sessionId)}`);
      const json = await res.json();
      if (!res.ok || !json.success) throw new Error(String(json.detail || json.message || 'Could not load chat history'));
      const restored = (json.history || []).map((item: any): ChatMessage => ({
        role: item.role === 'user' ? 'user' : item.role === 'system' ? 'system' : 'assistant',
        content: String(item.content || ''),
        action: item.action,
      }));
      setMessages(restored);
    } catch (e: any) {
      setMessages([]);
      setError(String(e?.message || e || 'Could not load chat history'));
    } finally {
      setHistoryLoading(false);
    }
  }, [apiRoot, sessionId]);

  React.useEffect(() => {
    loadSessions().catch(() => undefined);
  }, [loadSessions]);

  React.useEffect(() => {
    loadHistory().catch(() => undefined);
  }, [loadHistory]);

  function newChat() {
    const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\..+/, '');
    const next = `chat_${stamp}`;
    setSessionId(next);
    setMessages([]);
    setError(null);
  }

  function startRename(session: any) {
    setRenamingSession(session.session_id);
    setRenameValue(session.title || session.session_id);
  }

  async function saveRename() {
    if (!renamingSession || !renameValue.trim()) return;
    const res = await fetch(apiRoot + `/api/memory/sessions/${encodeURIComponent(renamingSession)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: renameValue.trim() }),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || !json.success) {
      setError(String(json.detail || json.message || 'Could not rename chat'));
      return;
    }
    setRenamingSession(null);
    setRenameValue('');
    await loadSessions();
  }

  async function onSubmit() {
    const text = instruction.trim();
    if (!text) return;

    setError(null);
    setLoading(true);

    const userMsg: ChatMessage = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInstruction('');

    try {
      let res: Response;
      if (files.length) {
        const fd = new FormData();
        fd.append('instruction', text);
        fd.append('session_id', sessionId);
        for (const f of files) fd.append('files', f);
        res = await fetch(apiRoot + '/api/conversation', {
          method: 'POST',
          body: fd,
        });
        setFiles([]);
        if (fileInputRef.current) fileInputRef.current.value = '';
        const json = await res.json();
        if (!res.ok || !json.success) {
          const msg = (json && json.message) ? String(json.message) : `Request failed (${res.status})`;
          throw new Error(msg);
        }
        const assistantText = json.message ? String(json.message) : '✓';
        const assistant: ChatMessage = {
          role: 'assistant',
          content: truncate(assistantText, 12000),
          success: true,
          action: json.action,
          route: json.meta?.route,
          artifacts: json.meta?.artifacts || [],
          suggestions: json.meta?.suggestions || [],
        };
        setMessages((prev) => [...prev, assistant]);
        loadSessions().catch(() => undefined);
      } else {
        res = await fetch(apiRoot + '/api/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ instruction: text, session_id: sessionId }),
        });
        await readStreamResponse(res);
        loadSessions().catch(() => undefined);
      }
    } catch (e: any) {
      const assistant: ChatMessage = {
        role: 'assistant',
        content: '✗ ' + String(e?.message || e || 'Request failed'),
        success: false,
      };
      setMessages((prev) => [...prev, assistant]);
      setError(String(e?.message || e || 'Request failed'));
    } finally {
      setLoading(false);
    }
  }

  async function readStreamResponse(res: Response) {
    if (!res.ok || !res.body) {
      const json = await res.json().catch(() => ({}));
      throw new Error(String(json.message || json.detail || `Request failed (${res.status})`));
    }

    const assistantIndex = messages.length + 1;
    setMessages((prev) => [...prev, { role: 'assistant', content: '', success: true }]);

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';
      for (const part of parts) {
        handleSsePart(part, assistantIndex);
      }
    }
    if (buffer.trim()) handleSsePart(buffer, assistantIndex);
  }

  function handleSsePart(part: string, assistantIndex: number) {
    const event = part.split('\n').find((line) => line.startsWith('event: '))?.slice(7).trim() || 'message';
    const raw = part.split('\n').find((line) => line.startsWith('data: '))?.slice(6) || '{}';
    const data = JSON.parse(raw);

    if (event === 'meta') {
      setMessages((prev) => prev.map((msg, index) => index === assistantIndex ? { ...msg, route: data.route } : msg));
    } else if (event === 'token') {
      setMessages((prev) => prev.map((msg, index) => (
        index === assistantIndex ? { ...msg, content: truncate(msg.content + String(data.text || ''), 12000), action: 'chat' } : msg
      )));
    } else if (event === 'final') {
      setMessages((prev) => prev.map((msg, index) => (
        index === assistantIndex
          ? {
              ...msg,
              content: truncate(String(data.message || ''), 12000),
              success: Boolean(data.success),
              action: data.action,
              route: data.meta?.route,
              artifacts: data.meta?.artifacts || [],
              suggestions: data.meta?.suggestions || [],
            }
          : msg
      )));
    } else if (event === 'error') {
      setMessages((prev) => prev.map((msg, index) => (
        index === assistantIndex ? { ...msg, content: '✗ ' + String(data.message || 'Request failed'), success: false } : msg
      )));
    }
  }

  return (
    <section className="chatWorkspace">
      <aside className="chatSessions panel">
        <div className="panelHeader">
          <h2>Chats</h2>
          <button className="btn primary" type="button" onClick={newChat}>New</button>
        </div>
        <div className="chatSessionList">
          {!sessions.some((s) => s.session_id === sessionId) ? (
            <button
              className="chatSession active"
              type="button"
              onClick={() => setSessionId(sessionId)}
            >
              <strong>{sessionId}</strong>
              <span>Current chat</span>
            </button>
          ) : null}
          {sessions.map((session) => (
            <div
              key={session.session_id}
              className={session.session_id === sessionId ? 'chatSession active' : 'chatSession'}
            >
              {renamingSession === session.session_id ? (
                <>
                  <input
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.currentTarget.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') saveRename().catch(() => undefined);
                      if (e.key === 'Escape') setRenamingSession(null);
                    }}
                    autoFocus
                  />
                  <div className="chatSessionActions">
                    <button className="btn primary" type="button" onClick={() => saveRename().catch(() => undefined)}>Save</button>
                    <button className="btn secondary" type="button" onClick={() => setRenamingSession(null)}>Cancel</button>
                  </div>
                </>
              ) : (
                <>
                  <button className="chatSessionMain" type="button" onClick={() => setSessionId(session.session_id)}>
                    <strong>{session.title || session.session_id}</strong>
                    <span>{session.message_count} messages · {session.last_at || ''}</span>
                  </button>
                  <button className="chatRename" type="button" onClick={() => startRename(session)} title="Rename chat">Rename</button>
                </>
              )}
            </div>
          ))}
        </div>
      </aside>

      <div className="card panel">
      <div className="chat">
        {historyLoading ? <div className="emptyState">Loading chat history...</div> : null}
        {messages.length === 0 ? (
          <div className="emptyState">
            Start this chat, or select an older chat from the left.
            <div className="hint">Uploaded files stay attached to this session for later follow-up questions.</div>
          </div>
        ) : null}

        {messages.map((m, idx) => (
          <div
            key={idx}
            className={m.role === 'user' ? 'bubble user' : 'bubble assistant'}
          >
            {m.route ? (
              <div className="routePill">
                {m.route.action || m.action || 'chat'}
                {m.route.module ? ` · ${m.route.module}` : ''}
              </div>
            ) : m.action ? (
              <div className="routePill">{m.action}</div>
            ) : null}
            <div className="bubbleText">{m.content}</div>
            {m.artifacts?.length ? <ArtifactList artifacts={m.artifacts} /> : null}
            {m.suggestions?.length ? (
              <div className="suggestionPills">
                {m.suggestions.map((suggestion, i) => (
                  <button key={i} type="button" onClick={() => setInstruction(suggestion)}>{suggestion}</button>
                ))}
              </div>
            ) : null}
          </div>
        ))}

        {loading ? (
          <div className="bubble assistant">
            <div className="bubbleText">Thinking...</div>
          </div>
        ) : null}
        <div ref={endRef} />
      </div>

      {error ? <div className="error">{error}</div> : null}

      <div className="composer">
        <textarea
          className="textarea"
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="Ask a question, give a data instruction, or attach files..."
          rows={3}
        />

        <div className="row">
          <input
            ref={fileInputRef}
            className="fileInput"
            type="file"
            multiple
            onChange={(e) => {
              const list = e.target.files ? Array.from(e.target.files) : [];
              setFiles(list);
            }}
          />
          <div className="actions">
            <button
              className="btn secondary"
              type="button"
              onClick={() => {
                setMessages([]);
                setError(null);
              }}
              disabled={loading}
            >
              Clear
            </button>
            <button
              className="btn primary"
              type="button"
              onClick={onSubmit}
              disabled={loading || !instruction.trim()}
            >
              Send
            </button>
          </div>
        </div>

        {files.length ? (
          <div className="fileList">
            {files.slice(0, 5).map((f, i) => (
              <span key={i} className="fileChip">
                {f.name}
              </span>
            ))}
            {files.length > 5 ? <span className="fileChip">+{files.length - 5} more</span> : null}
          </div>
        ) : null}
      </div>
      </div>
    </section>
  );
}

function ArtifactList({ artifacts }: { artifacts: any[] }) {
  return (
    <div className="artifactList">
      {artifacts.map((artifact, index) => {
        if (artifact.type === 'table') return <TableArtifact key={index} artifact={artifact} />;
        if (artifact.type === 'chart') return <ChartArtifact key={index} artifact={artifact} />;
        if (artifact.type === 'document') return <DocumentArtifact key={index} artifact={artifact} />;
        return null;
      })}
    </div>
  );
}

function TableArtifact({ artifact }: { artifact: any }) {
  const [filter, setFilter] = React.useState('');
  const rows = (artifact.rows || []).filter((row: any) => JSON.stringify(row).toLowerCase().includes(filter.toLowerCase()));
  const columns = artifact.columns || Object.keys(rows[0] || {});
  return (
    <div className="artifactCard">
      <div className="artifactHeader">
        <strong>{artifact.title || 'Table'}</strong>
        <span>{artifact.total || rows.length} rows</span>
      </div>
      <input value={filter} onChange={(e) => setFilter(e.currentTarget.value)} placeholder="Filter table" />
      <div className="artifactTableWrap">
        <table>
          <thead>
            <tr>{columns.map((column: string) => <th key={column}>{column}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row: any, i: number) => (
              <tr key={i}>{columns.map((column: string) => <td key={column}>{String(row[column] ?? '')}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ChartArtifact({ artifact }: { artifact: any }) {
  const series = artifact.series || [];
  const max = Math.max(1, ...series.map((item: any) => Number(item.value) || 0));
  return (
    <div className="artifactCard">
      <div className="artifactHeader">
        <strong>{artifact.title || 'Chart'}</strong>
        <span>{artifact.chart || 'bar'}</span>
      </div>
      <div className="chartBars">
        {series.map((item: any, i: number) => (
          <div className="chartBarRow" key={i}>
            <span>{item.label}</span>
            <div><b style={{ width: `${Math.max(5, (Number(item.value) / max) * 100)}%` }} /></div>
            <em>{item.value}</em>
          </div>
        ))}
      </div>
    </div>
  );
}

function DocumentArtifact({ artifact }: { artifact: any }) {
  function download() {
    const blob = new Blob([artifact.content || ''], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = artifact.filename || 'document.md';
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="artifactCard">
      <div className="artifactHeader">
        <strong>{artifact.title || 'Document'}</strong>
        <button className="btn secondary" type="button" onClick={download}>Download</button>
      </div>
      <pre className="documentPreview">{artifact.content}</pre>
    </div>
  );
}
