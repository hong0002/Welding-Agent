import { useEffect, useRef, useState } from 'react';
import { api, streamAgent, APIError, safeReplyReason } from './api';
import type { AgentHistory, AgentMessage, AgentProgress, AgentStatus } from './types';
import { AgentSessionError, restoreAgentSession } from './agentSession';

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
  const [initializing,setInitializing]=useState(true);
  const [connectionAttempt,setConnectionAttempt]=useState(0);
  const pending = useRef(false);
  const callbacks = useRef({ prepare, refresh });
  callbacks.current = { prepare, refresh };
  const initialization = useRef<Promise<AgentHistory> | null>(null);

  useEffect(() => {
    let active = true, attached=false, statusFailed=false;
    const load = () => {
      if(attached)return;
      attached=true;
      setInitializing(true);
      if(!initialization.current)initialization.current=restoreAgentSession();
      void initialization.current.then(async (history) => {
      if (!active) return;
      setSessionId(history.session_id); setMessages(history.messages);
      setInitializing(false);
      // A disconnected/reloaded tab must not start another run while the server is still working.
      while (history.running && active) {
        pending.current = true; setRunning(true);
        await pause();
        try {
          history = await api.agentHistory(history.session_id);
          if (active) setMessages(history.messages);
        } catch { if (active) setWarning('서버의 실행 상태를 확인하고 있습니다. 연결 복구 후 대화를 갱신합니다.'); }
      }
      if (active && history.active_job_id) {
        try { await callbacks.current.refresh(history.active_job_id); }
        catch { if(active)setWarning('대화는 연결됐지만 이전 작업 화면을 복원하지 못했습니다. 현재 작업을 다시 선택하세요.'); }
      }
      if (active) { pending.current = false; setRunning(false); }
      }).catch(cause => {
        if(active) {
          const failure=cause instanceof AgentSessionError?cause:new AgentSessionError('AGENT_HISTORY_LOAD_FAILED');
          setError(failure.message);setErrorCode(failure.code);setInitializing(false);
        }
      });
    };
    const check = async () => {
      try {
        const next=await api.agentStatus();if(!active)return;
        setStatus(next);
        if(next.enabled&&next.api_key_configured&&next.sdk_available&&['READY','RUNNING'].includes(next.state)) {
          if(statusFailed){setError('');setErrorCode('');statusFailed=false;}
          load();
        } else setInitializing(false);
      } catch {
        if(active) {
          setStatus(prev=>prev?{...prev,state:'ERROR'}:null);setInitializing(false);
          if(!initialization.current) {
            statusFailed=true;
            const failure=new AgentSessionError('AGENT_STATUS_UNAVAILABLE');
            setError(failure.message);setErrorCode(failure.code);
          }
        }
      }
    };
    void check(); const timer = window.setInterval(check, 10_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [connectionAttempt]);

  const reconnect = () => {
    if(pending.current||initializing)return;
    initialization.current=null;setSessionId('');setError('');setErrorCode('');setWarning('');
    setInitializing(true);setConnectionAttempt(value=>value+1);
  };

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

  return { status, messages, progress, running, error, errorCode, warning, send, reset, reconnect, initializing,
    canSend: Boolean(!initializing&&sessionId&&status?.enabled&&status.api_key_configured&&status.sdk_available&&['READY','RUNNING'].includes(status.state)),
    displayState: running ? 'RUNNING' : error ? 'ERROR' : initializing ? 'CONNECTING' : status?.state === 'RUNNING' ? 'READY' : status?.state ?? 'NOT CONFIGURED' };
}

export type AssistantController = ReturnType<typeof useAssistant>;
