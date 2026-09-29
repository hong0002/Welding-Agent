import type { Job, SimulatorLogs, SimulatorStatus } from './types';

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
  simulatorStatus: () => request<SimulatorStatus>('/simulator/status', { signal: AbortSignal.timeout(4_000) }),
  simulatorLogs: () => request<SimulatorLogs>('/simulator/logs', { signal: AbortSignal.timeout(4_000) }),
  startSimulator: () => request<SimulatorStatus>('/simulator/start', json({})),
  runSimulatorSample: () => request<SimulatorStatus>('/simulator/run-sample', json({})),
  stopSimulator: () => request<SimulatorStatus>('/simulator/stop', json({})),
  health: () => request<{ status: string }>('/health', { signal: AbortSignal.timeout(4_000) }),
  upload: (file: Blob, name: string) => {
    const body = new FormData(); body.append('file', file, name);
    return request<Job>('/scenes/upload', { method: 'POST', body });
  },
  mask: (jobId: string, mask: Blob) => {
    const body = new FormData(); body.append('job_id', jobId); body.append('file', mask, 'mask.png');
    return request<Job>('/masks/manual', { method: 'POST', body });
  },
  parse: (jobId: string, instruction: string, skipRegions: number[] = []) => request<Job>('/instructions/parse', json({
    job_id: jobId, instruction, region_selection: { skip_regions: skipRegions },
  })),
  plan: (jobId: string) => request<Job>('/weld/plan', json({ job_id: jobId })),
};
