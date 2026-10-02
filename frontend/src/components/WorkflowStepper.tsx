import type { SimulatorState, State } from '../types';
import { Icon } from './Icon';
import type { InspectorTab } from './Inspector';

const states: State[] = ['SCENE_READY', 'MASK_READY', 'INSTRUCTION_READY', 'ROUGH_PATH_READY', 'VLA_REFINED'];
const phases = [
  { name: 'PREPARE', steps: ['Scene', 'Mask', 'Instruction'], start: 0 },
  { name: 'PLAN', steps: ['Rough', 'VLA ready'], start: 3 },
  { name: 'PREVIEW', steps: ['Simulator'], start: 5 },
];

export function WorkflowStepper({ state, simulatorState, activeTab, onNavigate }: {
  state: State; simulatorState: SimulatorState | 'RUNNING_PREVIEW' | null; activeTab: InspectorTab;
  onNavigate: (target: InspectorTab | 'workspace') => void;
}) {
  const completed = ['VLA_READY','VALIDATED'].includes(state)?4:states.indexOf(state);
  const simulationActive = ['STARTING', 'READY', 'RUNNING_SAMPLE', 'RUNNING_PREVIEW'].includes(simulatorState ?? '');
  const current = completed + 1;
  return <nav className="workflow-stepper" aria-label="Workflow progress">
    {phases.map((phase) => <div className={`workflow-phase phase-${phase.name.toLowerCase()}`} key={phase.name}>
      <div className="phase-label">{phase.name}{phase.start === 5 && <span>Simulation only</span>}</div>
      <ol start={phase.start + 1}>
        {phase.steps.map((original, offset) => {
          const label=original;
          const index = phase.start + offset;
          const target = index < 2 ? 'workspace' : index === 2 ? 'command' : index < 5 ? 'path' : 'simulator';
          const status = index === 5 && simulatorState === 'FAILED' ? 'failed'
            : index <= completed ? 'completed' : (index < 5 && index === current && state!=='VLA_READY') || (index === 5 && simulationActive) ? 'current' : 'pending';
          return <li key={label} className={`step ${status}`} aria-current={status === 'current' ? 'step' : undefined}>
            <button className="step-link" aria-label={label} aria-controls={target === 'workspace' ? 'workspace' : `panel-${target}`} aria-pressed={target === activeTab} onClick={() => onNavigate(target)}>
            <span className="step-marker" aria-hidden="true">{status === 'completed' ? <Icon name="check" size={13} /> : status === 'failed' ? '!' : String(index + 1).padStart(2, '0')}</span>
            <span>{label}</span><span className="sr-only"> · {status}</span>
            </button>
          </li>;
        })}
      </ol>
    </div>)}
  </nav>;
}
