import type { Stroke } from '../types';
import { Icon } from './Icon';

type Props = {
  tool: Stroke['tool']; brushSize: number; disabled: boolean;
  canUndo: boolean; canClear: boolean;
  onTool: (tool: Stroke['tool']) => void; onSize: (size: number) => void;
  onUndo: () => void; onClear: () => void;
};

export function WorkspaceToolbar({ tool, brushSize, disabled, canUndo, canClear, onTool, onSize, onUndo, onClear }: Props) {
  return <div className="workspace-toolbar" aria-label="Annotation tools">
    <div className="tool-group" role="group" aria-label="Drawing tool">
      <button className={tool === 'brush' ? 'selected' : ''} aria-pressed={tool === 'brush'} onClick={() => onTool('brush')} disabled={disabled}><Icon name="brush" />Brush</button>
      <button className={tool === 'eraser' ? 'selected' : ''} aria-pressed={tool === 'eraser'} onClick={() => onTool('eraser')} disabled={disabled}><Icon name="eraser" />Eraser</button>
    </div>
    <label className="range-control brush-size">Size<input aria-label="Brush size" type="range" min="2" max="120" value={brushSize} disabled={disabled} onChange={(event) => onSize(Number(event.target.value))} /><output>{brushSize}<span> px</span></output></label>
    <div className="history-tools" role="group" aria-label="Mask history">
      <button className="icon-button" aria-label="Undo" title="Undo" disabled={!canUndo} onClick={onUndo}><Icon name="undo" /></button>
      <button className="icon-button danger-hover" aria-label="Clear" title="Clear" disabled={!canClear} onClick={onClear}><Icon name="clear" /></button>
    </div>
  </div>;
}
