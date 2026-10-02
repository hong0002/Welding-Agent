import { api, APIError } from './api';
import type { AgentHistory } from './types';

export const SESSION_KEY = 'welding-agent-conversation';
const uuid = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i;
const messages = {
  AGENT_SESSION_CREATE_FAILED: '대화 세션을 생성하지 못했습니다. 잠시 후 다시 연결하세요.',
  AGENT_SESSION_ORIGIN_REJECTED: '대화 세션 요청의 웹 Origin이 허용되지 않았습니다. Backend의 Agent Origin 설정을 확인하세요.',
  AGENT_SESSION_NOT_FOUND: '생성된 대화 세션을 찾을 수 없습니다. 다시 연결하세요.',
  AGENT_HISTORY_LOAD_FAILED: '대화 기록을 불러오지 못했습니다. 기존 세션을 유지했으므로 다시 연결하세요.',
  AGENT_STATUS_UNAVAILABLE: 'Agent 상태를 확인하지 못했습니다. 연결 상태를 확인하세요.',
} as const;

export class AgentSessionError extends Error {
  constructor(readonly code:keyof typeof messages) { super(messages[code]); }
}

export async function restoreAgentSession():Promise<AgentHistory> {
  let saved='';
  try { saved=localStorage.getItem(SESSION_KEY)??''; } catch { /* Optional persistence. */ }
  if(uuid.test(saved)) {
    try { return await api.agentHistory(saved); }
    catch(cause) {
      // A temporary outage/403/500 is not an expired session; never discard its ID.
      if(!(cause instanceof APIError&&[404,410].includes(cause.status)))
        throw new AgentSessionError('AGENT_HISTORY_LOAD_FAILED');
    }
  }
  let session:{session_id:string};
  try {
    session=await api.createAgentSession();
    if(!uuid.test(session.session_id))throw new Error('Invalid session response');
  } catch(cause) {
    throw new AgentSessionError(cause instanceof APIError&&cause.status===403?
      'AGENT_SESSION_ORIGIN_REJECTED':'AGENT_SESSION_CREATE_FAILED');
  }
  try { localStorage.setItem(SESSION_KEY,session.session_id); } catch { /* In-memory fallback. */ }
  try { return await api.agentHistory(session.session_id); }
  catch(cause) {
    throw new AgentSessionError(cause instanceof APIError&&[404,410].includes(cause.status)?
      'AGENT_SESSION_NOT_FOUND':'AGENT_HISTORY_LOAD_FAILED');
  }
}
