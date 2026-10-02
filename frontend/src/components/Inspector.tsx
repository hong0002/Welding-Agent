import { useRef, type ReactNode } from 'react';
import { Icon } from './Icon';
import type { SimulatorState } from '../types';
import { statusTone } from './StatusBadge';

export type InspectorTab = 'command' | 'path' | 'simulator';
const tabs: { id: InspectorTab; label: string; icon: string }[] = [
  { id: 'command', label: 'Assistant', icon: 'command' },
  { id: 'path', label: '경로 계획', icon: 'path' },
  { id: 'simulator', label: '시뮬레이션', icon: 'robot' },
];

export function Inspector({ active, onChange, panels, simulatorState, nextAction,summary }: {
  active: InspectorTab; onChange: (tab: InspectorTab) => void;
  panels: Record<InspectorTab, ReactNode>; simulatorState: SimulatorState | null; nextAction: ReactNode;
  summary?:ReactNode;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  return <aside className="inspector" id="inspector" aria-label="Workspace inspector">
    <div className="inspector-heading"><span className="utility-label">INSPECTOR</span><span>작업 제어</span></div>
    <div className="inspector-tabs" role="tablist" aria-label="Inspector sections">
      {tabs.map((tab, index) => <button key={tab.id} ref={(node) => { refs.current[index] = node; }}
        type="button" role="tab" id={`tab-${tab.id}`} aria-selected={active === tab.id}
        aria-controls={`panel-${tab.id}`} tabIndex={active === tab.id ? 0 : -1}
        onClick={() => onChange(tab.id)} onKeyDown={(event) => {
          let next = index;
          if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
          else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
          else if (event.key === 'Home') next = 0;
          else if (event.key === 'End') next = tabs.length - 1;
          else return;
          event.preventDefault(); onChange(tabs[next].id); refs.current[next]?.focus();
        }}><Icon name={tab.icon} size={16} />{tab.label}{tab.id === 'simulator' && <span className={`tab-state tone-${statusTone(simulatorState)}`} title={`Simulator ${simulatorState ?? 'offline'}`} aria-hidden="true" />}</button>)}
    </div>
    {summary}
    {tabs.map((tab) => <div key={tab.id} id={`panel-${tab.id}`} role="tabpanel" aria-labelledby={`tab-${tab.id}`} hidden={active !== tab.id} className="inspector-body" tabIndex={0}>{panels[tab.id]}</div>)}
    {nextAction}
    <div className="inspector-footer"><Icon name="crosshair" size={14} /><span>Human decides. Models propose.</span></div>
  </aside>;
}
