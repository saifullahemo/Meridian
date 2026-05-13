import React, { useMemo, useRef, useState } from 'react';
import type { ChatMessage } from './App';

function truncate(s: string, n: number) {
  if (s.length <= n) return s;
  return s.slice(0, n) + `\n\n[Truncated ${n} chars]`;
}

export default function ConversationMode({
  apiBaseUrl,
  sessionId,
}: {
  apiBaseUrl: string;
  sessionId: string;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [instruction, setInstruction] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const endRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  React.useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const apiRoot = useMemo(() => apiBaseUrl.replace(/\/$/, ''), [apiBaseUrl]);

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
        };
        setMessages((prev) => [...prev, assistant]);
      } else {
        res = await fetch(apiRoot + '/api/chat/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ instruction: text, session_id: sessionId }),
        });
        await readStreamResponse(res);
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
    <div className="card panel">
      <div className="chat">
        {messages.length === 0 ? (
          <div className="emptyState">
            Ask anything, manage your data, or attach files for document-aware help.
            <div className="hint">Without files, requests are routed to actions like save, read, search, summarize, and chat.</div>
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
  );
}
