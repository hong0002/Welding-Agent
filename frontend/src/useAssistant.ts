import { useEffect, useRef, useState } from 'react';
import { api, streamAgent, APIError, safeReplyReason } from './api';
import type { AgentHistory, AgentMessage, AgentProgress, AgentStatus } from './types';

const SESSION_KEY = 'welding-agent-conversation';
const pause = () => new Promise((resolve) => window.setTimeout(resolve, 1500));

export function useAssistant(prepare: (message:string) => Promise<string | null>, refresh: (id: string) => Promise<void>) {
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [sessionId, setSessionId] = useState('');
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [progress, setProgress] = useState<AgentProgress[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [errorCode, setErrorCode] = useState('');
  const [warning, setWarning] = useState('');
  const pending = useRef(false);
  const callbacks = useRef({ prepare, refresh });
  callbacks.current = { prepare, refresh };
  const initialization = useRef<Promise<AgentHistory> | null>(null);

  useEffect(() => {
    let active = true;
    if (!initialization.current) initialization.current = (async () => {
      let saved = '';
      try { saved = localStorage.getItem(SESSION_KEY) ?? ''; } catch { /* Storage is optional. */ }
      if (/^[\da-f-]{36}$/i.test(saved)) {
        try { return await api.agentHistory(saved); } catch { /* Expired local session. */ }
      }
      const session = await api.createAgentSession();
      try { localStorage.setItem(SESSION_KEY, session.session_id); } catch { /* In-memory fallback. */ }
      return api.agentHistory(session.session_id);
    })();
    void initialization.current.then(async (history) => {
      if (!active) return;
      setSessionId(history.session_id); setMessages(history.messages);
      // A disconnected/reloaded tab must not start another run while the server is still working.
      while (history.running && active) {
        pending.current = true; setRunning(true);
        await pause();
        try {
          history = await api.agentHistory(history.session_id);
          if (active) setMessages(history.messages);
        } catch { if (active) setWarning('서버의 실행 상태를 확인하고 있습니다. 연결 복구 후 대화를 갱신합니다.'); }
      }
      if (active && history.active_job_id) await callbacks.current.refresh(history.active_job_id);
      if (active) { pending.current = false; setRunning(false); }
    }).catch(() => { if (active) setError('대화를 불러오지 못했습니다. Backend 연결을 확인한 후 페이지를 새로고침하세요.'); });
    const check = async () => {
      try { const next = await api.agentStatus(); if (active) setStatus(next); }
      catch { if (active) setStatus((prev) => prev ? { ...prev, state: 'ERROR' } : null); }
    };
    void check(); const timer = window.setInterval(check, 10_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const send = async (message: string, clarificationId?:string) => {
    const text = message.trim();
    if (!text || !sessionId || pending.current) return;
    pending.current = true; setRunning(true); setError(''); setErrorCode(''); setWarning(''); setProgress([]);
    setMessages((prev) => [...prev, { role: 'user', text }]);
    let submitted = false, jobId: string | null = null, reply = '';
    try {
      jobId = await callbacks.current.prepare(text);
      submitted = true;
      await streamAgent(sessionId, jobId, text, async ({ event, data }) => {
        if (event === 'assistant_delta') {
          reply += data.text;
          setMessages((prev) => [...(prev.at(-1)?.role === 'assistant' ? prev.slice(0, -1) : prev), { role: 'assistant', text: reply }]);
        } else if (event === 'tool_started' || event === 'tool_completed') {
          setProgress((prev) => [...prev.filter((item) => item.call_id !== data.call_id), data]);
        } else if (event === 'workspace_updated') {
          try { await callbacks.current.refresh(data.job_id); }
          catch { setWarning('작업 화면을 갱신하지 못했습니다. 연결 복구 후 현재 작업을 새로고침하세요.'); }
        } else if (event === 'error') {setError(data.message);setErrorCode(safeReplyReason(data.code));}
        else if (event === 'warning') setWarning([safeReplyReason(data.code),data.message].filter(Boolean).join(' · '));
      }, clarificationId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Agent 요청에 실패했습니다.');
      setErrorCode(cause instanceof APIError ? cause.code : '');
      if (submitted) {
        // Never automatically resubmit a message: reconcile the persisted run instead.
        let settled = false;
        while (!settled) {
          try {
            const history = await api.agentHistory(sessionId);
            setMessages(history.messages);
            settled = !history.running;
            if (settled && jobId) await callbacks.current.refresh(jobId);
          } catch {
            // Keep controls locked until the backend can establish whether this run finished.
            setWarning('서버의 실행 상태를 확인하고 있습니다. 연결이 복구되면 결과를 갱신합니다.');
          }
          if (!settled) await pause();
        }
      }
    } finally {
      pending.current = false; setRunning(false);
    }
  };

  const reset = async () => {
    if (!sessionId || pending.current) return;
    pending.current = true; setRunning(true);
    try { await api.resetAgentSession(sessionId); setMessages([]); setProgress([]); setError(''); setErrorCode(''); setWarning(''); }
    catch (cause) { setError(cause instanceof Error ? cause.message : '대화 초기화에 실패했습니다.'); }
    finally { pending.current = false; setRunning(false); }
  };

  return { status, messages, progress, running, error, errorCode, warning, send, reset,
    canSend: Boolean(sessionId && status?.enabled && status.api_key_configured && status.sdk_available),
    displayState: running ? 'RUNNING' : error ? 'ERROR' : status?.state === 'RUNNING' ? 'READY' : status?.state ?? 'NOT CONFIGURED' };
}

export type AssistantController = ReturnType<typeof useAssistant>;
