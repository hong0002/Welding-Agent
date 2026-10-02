import type { AgentEvent, AgentHistory, AgentStatus, Job, ModelStatuses, SimulatorLogs, SimulatorStatus, PreviewCapabilities, PreviewFrames, YoloOverlay } from './types';

const replyReasonCodes = new Set(['CLARIFICATION_STALE','APPROVAL_CHANGED','CLARIFICATION_PROVENANCE_MISMATCH',
  'CLARIFICATION_ANSWER_UNSUPPORTED','CLARIFICATION_RECOVERY_REQUIRED','TRAJECTORY3_ADMISSION_FAILED',
  'TRAJECTORY3_NATIVE_FAILED','TRAJECTORY3_TIMEOUT','TRAJECTORY3_OUTPUT_INVALID','TRAJECTORY3_NEEDS_CLARIFICATION_AGAIN']);
export const safeReplyReason = (value:unknown):string => typeof value==='string'&&replyReasonCodes.has(value)?value:'';
const previewReasonCodes = new Set(['PREVIEW_FAMILY_UNSUPPORTED','PREVIEW_SAMPLE_ASSET_MISSING','PREVIEW_H5_MISMATCH',
  'PREVIEW_OBJ_MISSING','PREVIEW_PATH_SUPPORTED_ROBOT_PENDING','PREVIEW_POLICY_NOT_READY',
  'CURRENT_PREVIEW_FRAME_STALE','CURRENT_PREVIEW_FRAME_UNAVAILABLE','CURRENT_PREVIEW_FRAME_PENDING','CURRENT_PREVIEW_NOT_ACTIVE','CURRENT_PREVIEW_ARTIFACT_INVALID','CURRENT_PREVIEW_ASSET_MISSING','CURRENT_PREVIEW_LAUNCHER_NOT_CONFIGURED',
  'CURRENT_PREVIEW_LAUNCHER_INVALID','CURRENT_PREVIEW_CONFIGURATION_INVALID',
  'SIMULATOR2_SAMPLE_UNSUPPORTED','SIMULATOR2_H5_MISSING','SIMULATOR2_OBJ_MISSING','SIMULATOR2_FRAME_MISMATCH',
  'SIMULATOR2_SCENE_BUILD_FAIL','SIMULATOR2_IK_FAIL','SIMULATOR2_PLAYBACK_FAIL','SIMULATOR2_CAPTURE_WARNING',
  'SIMULATOR_STP_SOURCE_INVALID','SIMULATOR_STP_MODE_INVALID',
  'SIMULATOR_STP_SCENE_BUILD_FAIL','SIMULATOR_STP_IK_FAIL','SIMULATOR_STP_PLAYBACK_FAIL','SIMULATOR_STP_CAPTURE_WARNING',
  'SIMULATOR_STP_UNVALIDATED_SCENE','SIMULATOR_STP_ROBOT_PREFLIGHT_REQUIRED','SIMULATOR_STP_SAMPLE_UNSUPPORTED','SIMULATOR_STP_H5_MISSING','SIMULATOR_STP_OBJ_MISSING','SIMULATOR_STP_FRAME_MISMATCH',
  'CAPTURE_ASCII_PATH_UNAVAILABLE','CAPTURE_API_FAILED','CAPTURE_FILE_WRITE_FAILED',
  'CAPTURE_FILE_MISSING_TIMEOUT','CAPTURE_ZERO_BYTE','CAPTURE_FILE_INCOMPLETE','CAPTURE_EVIDENCE_MISSING',
  'SIMULATOR2_ROBOT_PREFLIGHT_REQUIRED','SIMULATOR2_UNVALIDATED_SCENE']);
export const safePreviewReason = (value:unknown):string => typeof value==='string'&&previewReasonCodes.has(value)?value:'';
const agentHTTPMessages:Record<string,string>={
  model_unavailable:'OpenAI 모델을 사용할 수 없습니다. 모델 접근 권한과 설정을 확인하세요.',
  agent_not_configured:'GPT Agent 설정이 필요합니다. 수동 기능은 계속 사용할 수 있습니다.',
  authentication_failed:'OpenAI API 인증에 실패했습니다. Backend 설정을 확인하세요.',
  rate_limit:'OpenAI 사용 한도에 도달했습니다. 잠시 후 다시 시도하세요.',
  run_in_progress:'이 대화 또는 작업에서 요청이 실행 중입니다. 완료 후 다시 시도하세요.',
  session_not_found:'대화 세션을 찾을 수 없습니다. 페이지를 새로고침하여 다시 연결하세요.',
  invalid_request:'Agent 요청의 Origin 또는 입력 형식이 허용되지 않았습니다.',
};
export class APIError extends Error {
  readonly code:string;
  readonly status:number;
  constructor(message:string,code:unknown,status=0){super(message);this.code=safeReplyReason(code)||safePreviewReason(code)||(typeof code==='string'&&(code==='AGENT_STREAM_UNAVAILABLE'||Object.hasOwn(agentHTTPMessages,code))?code:'');this.status=status;}
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { ...options, signal: options.signal ?? AbortSignal.timeout(30_000) });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === 'string' ? body.detail : `요청 실패 (${response.status}). 입력값을 확인하세요.`;
    throw new APIError(detail,body.code,response.status);
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
  yolo: (id:string) => request<YoloOverlay>(`/weld/${id}/yolo`),
  simulatorStatus: () => request<SimulatorStatus>('/simulator/status', { signal: AbortSignal.timeout(4_000) }),
  simulator2Preflight: (jobId:string) => request<PreviewCapabilities>('/simulator/current-vla/preview-preflight', {...json({job_id:jobId}),signal:AbortSignal.timeout(190_000)}),
  simulatorLogs: () => request<SimulatorLogs>('/simulator/logs', { signal: AbortSignal.timeout(4_000) }),
  startSimulator: () => request<SimulatorStatus>('/simulator/start', json({})),
  runSimulatorSample: () => request<SimulatorStatus>('/simulator/run-sample', json({})),
  stopSimulator: () => request<SimulatorStatus>('/simulator/stop', json({})),
  previewCurrentVLA: (jobId:string,kind:'robot'|'path'='robot') => request<SimulatorStatus>(`/simulator/preview-current-vla${kind==='path'?'/path':''}`, {...json({job_id:jobId}),signal:AbortSignal.timeout(90_000)}),
  previewCapabilities:(jobId:string)=>request<PreviewCapabilities>(`/simulator/current-vla/capabilities?job_id=${encodeURIComponent(jobId)}`),
  previewFrames:(jobId:string,artifactId:string)=>request<PreviewFrames>(`/simulator/current-preview/frames?job_id=${encodeURIComponent(jobId)}&artifact_id=${encodeURIComponent(artifactId)}`,{signal:AbortSignal.timeout(4_000),cache:'no-store'}),
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
  onEvent: (event: AgentEvent) => Promise<void>, clarificationId?:string) {
  let response:Response;
  try { response = await fetch('/api/agent/chat/stream', {
    ...json({ session_id: sessionId, job_id: jobId, message, ...(clarificationId?{clarification_id:clarificationId}:{}) }), signal: AbortSignal.timeout(1_260_000),
  }); } catch {
    throw new APIError('Agent 응답 연결에 실패했습니다. 서버의 실행 상태를 확인합니다.','AGENT_STREAM_UNAVAILABLE');
  }
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    const replyCode=safeReplyReason(body.code);
    const knownCode=typeof body.code==='string'&&Object.hasOwn(agentHTTPMessages,body.code)?body.code:'';
    throw new APIError(replyCode&&typeof body.detail==='string'?body.detail:knownCode?agentHTTPMessages[knownCode]:'Agent 응답 연결을 사용할 수 없습니다.',
      replyCode||knownCode||'AGENT_STREAM_UNAVAILABLE',response.status);
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
