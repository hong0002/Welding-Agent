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
      <button className={tool === 'brush' ? 'selected' : ''} aria-pressed={tool === 'brush'} onClick={() => onTool('brush')} disabled={disabled}><Icon name="brush" />브러시</button>
      <button className={tool === 'eraser' ? 'selected' : ''} aria-pressed={tool === 'eraser'} onClick={() => onTool('eraser')} disabled={disabled}><Icon name="eraser" />지우개</button>
    </div>
    <label className="range-control brush-size">크기<input aria-label="Brush size" type="range" min="2" max="120" value={brushSize} disabled={disabled} onChange={(event) => onSize(Number(event.target.value))} /><output>{brushSize}<span> px</span></output></label>
    <div className="history-tools" role="group" aria-label="Mask history">
      <button className="icon-button" aria-label="실행 취소" title="실행 취소" disabled={!canUndo} onClick={onUndo}><Icon name="undo" /></button>
      <button className="icon-button danger-hover" aria-label="전체 지우기" title="전체 지우기" disabled={!canClear} onClick={onClear}><Icon name="clear" /></button>
    </div>
  </div>;
}
