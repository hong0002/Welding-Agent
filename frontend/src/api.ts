import type { AgentEvent, AgentHistory, AgentStatus, Job, ModelStatuses, SimulatorLogs, SimulatorStatus } from './types';

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { ...options, signal: options.signal ?? AbortSignal.timeout(30_000) });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === 'string' ? body.detail : `요청 실패 (${response.status}). 입력값을 확인하세요.`;
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export const api = {
  modelStatus: () => request<ModelStatuses>('/models/status', { signal: AbortSignal.timeout(4_000) }),
  agentStatus: () => request<AgentStatus>('/agent/status'),
  createAgentSession: () => request<{ session_id: string }>('/agent/sessions', json({})),
  agentHistory: (id: string) => request<AgentHistory>(`/agent/sessions/${id}/history`),
  resetAgentSession: (id: string) => request<AgentHistory>(`/agent/sessions/${id}/reset`, json({})),
  getJob: (id: string) => request<Job>(`/weld/${id}`),
  simulatorStatus: () => request<SimulatorStatus>('/simulator/status', { signal: AbortSignal.timeout(4_000) }),
  simulatorLogs: () => request<SimulatorLogs>('/simulator/logs', { signal: AbortSignal.timeout(4_000) }),
  startSimulator: () => request<SimulatorStatus>('/simulator/start', json({})),
  runSimulatorSample: () => request<SimulatorStatus>('/simulator/run-sample', json({})),
  stopSimulator: () => request<SimulatorStatus>('/simulator/stop', json({})),
  previewCurrentVLA: (jobId:string,kind:'robot'|'path'='robot') => request<SimulatorStatus>(`/simulator/preview-current-vla${kind==='path'?'/path':''}`, {...json({job_id:jobId}),signal:AbortSignal.timeout(90_000)}),
  health: () => request<{ status: string }>('/health', { signal: AbortSignal.timeout(4_000) }),
  upload: (file: Blob, name: string) => {
    const body = new FormData(); body.append('file', file, name);
    return request<Job>('/scenes/upload', { method: 'POST', body });
  },
  loadSample:(sampleId:string)=>request<Job>('/scenes/sample',json({sample_id:sampleId})),
  roughMode:(jobId:string,mode:'baseline_2d'|'native_3d')=>request<Job>('/weld/rough-mode',json({job_id:jobId,mode})),
  guidedVLA:(jobId:string)=>request<Job>(`/weld/${jobId}/guided-vla`,{...json({}),signal:AbortSignal.timeout(660_000)}),
  mask: (jobId: string, mask: Blob, editedFrom?: string,viewId?:string) => {
    const body = new FormData(); body.append('job_id', jobId); body.append('file', mask, 'mask.png');
    if (editedFrom) body.append('edited_from_mask_id', editedFrom);
    if(viewId)body.append('view_id',viewId);
    return request<Job>('/masks/manual', { method: 'POST', body });
  },
  approveMask: (jobId: string, maskId: string,viewId?:string) => request<Job>('/masks/approve', json({ job_id: jobId, mask_id: maskId,view_id:viewId })),
  segment: (jobId: string, instruction: string) => request<Job>('/masks/automatic', {
    ...json({ job_id: jobId, instruction }), signal: AbortSignal.timeout(960_000),
  }),
  parse: (jobId: string, instruction: string, skipRegions: number[] = []) => request<Job>('/instructions/parse', json({
    job_id: jobId, instruction, region_selection: { skip_regions: skipRegions },
  })),
  plan: (jobId: string) => request<Job>('/weld/plan', { ...json({ job_id: jobId }), signal: AbortSignal.timeout(960_000) }),
};

export async function streamAgent(sessionId: string, jobId: string | null, message: string,
  onEvent: (event: AgentEvent) => Promise<void>) {
  const response = await fetch('/api/agent/chat/stream', {
    ...json({ session_id: sessionId, job_id: jobId, message }), signal: AbortSignal.timeout(1_260_000),
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : 'Agent 연결에 실패했습니다.');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '', completed = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
        const lines = frame.split('\n');
        const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim();
        const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n');
        if (event && data) {
          const parsed = { event, data: JSON.parse(data) } as AgentEvent;
          await onEvent(parsed);
          if (event === 'done') completed = true;
        }
      }
      if (done) break;
    }
    if (!completed) throw new Error('응답 연결이 끊겼습니다. 서버의 작업 상태를 확인합니다.');
  } finally { reader.releaseLock(); }
}
