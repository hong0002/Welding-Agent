import type { ReactNode } from 'react';

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    brush: <><path d="m14 4 6 6-8 8-6-6 8-8Z" /><path d="M6 12c-4 2-1 5-4 8 5 0 7-1 8-4" /></>,
    eraser: <><path d="m13 3 8 8-9 10H7l-5-5L2 16 13 3Z" /><path d="m7 11 8 8M12 21h10" /></>,
    upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6" /></>,
    undo: <><path d="M4 8h10a6 6 0 0 1 0 12M4 8l5-5M4 8l5 5" /></>,
    clear: <><path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7" /></>,
    arrow: <><path d="M4 12h16m-6-6 6 6-6 6" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    layers: <><path d="m12 3 10 6-10 6L2 9l10-6ZM2 13l10 6 10-6M2 17l10 6 10-6" /></>,
    image: <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8" cy="8" r="1" /><path d="m3 17 6-6 4 4 3-3 5 5" /></>,
    download: <><path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4" /></>,
    command: <><path d="m5 6 5 6-5 6M13 18h6" /></>,
    path: <><circle cx="5" cy="18" r="2" /><circle cx="19" cy="6" r="2" /><path d="M5 16V8a3 3 0 0 1 6 0v8a3 3 0 0 0 6 0V8" /></>,
    robot: <><path d="M4 21h16M8 21v-4l5-3-5-6M8 8l5-4 6 4-3 4M18 11l3 2-2 3" /><circle cx="8" cy="8" r="2" /><circle cx="13" cy="14" r="2" /></>,
    play: <path d="m8 4 12 8-12 8V4Z" />,
    stop: <rect x="6" y="6" width="12" height="12" rx="1" />,
    chevron: <path d="m7 10 5 5 5-5" />,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    alert: <><path d="m12 3 10 18H2L12 3Z" /><path d="M12 9v5m0 3h.01" /></>,
    crosshair: <><circle cx="12" cy="12" r="7" /><path d="M12 2v5m0 10v5M2 12h5m10 0h5" /></>,
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name] ?? paths.layers}</svg>;
}
