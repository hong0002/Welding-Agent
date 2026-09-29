import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import type { SimulatorLogs, SimulatorStatus } from './types';

// Existing polling and action guards stay mounted across Inspector tabs.
export function useSimulator() {
  const [status, setStatus] = useState<SimulatorStatus | null>(null);
  const [logs, setLogs] = useState<SimulatorLogs['entries']>([]);
  const [online, setOnline] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const revision = useRef(0);
  const pending = useRef(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    let active = true;
    let timer: number;
    const poll = async () => {
      const current = revision.current;
      if (!pending.current) {
        try {
          const [next, output] = await Promise.all([api.simulatorStatus(), api.simulatorLogs()]);
          if (active && current === revision.current) {
            setStatus(next); setLogs(output.entries); setOnline(true);
          }
        } catch {
          if (active && current === revision.current) { setOnline(false); }
        }
      }
      if (active) timer = window.setTimeout(poll, 1500);
    };
    void poll();
    return () => { active = false; alive.current = false; window.clearTimeout(timer); };
  }, []);

  const act = async (action: () => Promise<SimulatorStatus>) => {
    if (pending.current) return;
    pending.current = true; revision.current += 1; setBusy(true); setError('');
    try {
      const next = await action();
      if (alive.current) { setStatus(next); setOnline(true); }
    } catch (cause) {
      if (alive.current) setError(cause instanceof Error ? cause.message : 'Simulator 요청 실패');
    } finally {
      revision.current += 1; pending.current = false;
      if (alive.current) setBusy(false);
    }
  };

  return { status, logs, online, busy, error, act };
}

export type SimulatorController = ReturnType<typeof useSimulator>;
