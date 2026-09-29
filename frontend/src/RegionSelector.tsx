import type { MaskRegion } from './types';

type Props = {
  regions: MaskRegion[];
  skipped: number[];
  discarded: number;
  disabled: boolean;
  onChange: (regionIds: number[]) => void;
};

export function RegionSelector({ regions, skipped, discarded, disabled, onChange }: Props) {
  return <fieldset className="region-selector" disabled={disabled}>
    <legend data-testid="region-count">Regions: {regions.length}</legend>
    <p>용접할 영역을 선택하세요. 해제한 영역은 경로에서 제외됩니다.</p>
    <div className="region-options">
      {regions.map((region) => <label key={region.region_id}>
        <input type="checkbox" aria-label={`Region ${region.region_id} 포함`}
          checked={!skipped.includes(region.region_id)}
          onChange={(event) => onChange(event.target.checked
            ? skipped.filter((id) => id !== region.region_id)
            : [...skipped, region.region_id].sort((a, b) => a - b))} />
        <span>Region {region.region_id}</span>
        <small>{region.pixel_area.toLocaleString()} px</small>
      </label>)}
    </div>
    {discarded > 0 && <p>최소 면적보다 작은 영역 {discarded}개는 제외했습니다.</p>}
    {regions.length === skipped.length && <p className="region-empty">최소 한 영역을 선택하세요.</p>}
  </fieldset>;
}
