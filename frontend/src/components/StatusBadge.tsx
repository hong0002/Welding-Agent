export type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'active';

export function statusTone(state: string | null | undefined): Tone {
  if (['READY', 'SUCCEEDED', 'passed', 'CONFIRMED'].includes(state ?? '')) return 'success';
  if (['FAILED', 'failed'].includes(state ?? '')) return 'danger';
  if (['STARTING', 'PREPARING', 'QUEUED'].includes(state ?? '')) return 'warning';
  if (['RUNNING_SAMPLE', 'RUNNING_PREVIEW', 'RUNNING'].includes(state ?? '')) return 'active';
  return 'neutral';
}

export function StatusBadge({ children, tone = 'neutral', testId }: {
  children: React.ReactNode; tone?: Tone; testId?: string;
}) {
  return <span className={`status-badge tone-${tone}`} data-testid={testId}><i aria-hidden="true" />{children}</span>;
}
