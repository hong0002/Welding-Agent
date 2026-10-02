import { Icon } from './Icon';

export function NextAction({ destination, onContinue }: {
  destination: 'path' | 'simulator'; onContinue: () => void;
}) {
  const path = destination === 'path';
  return <section className="inspector-next" aria-label="다음 단계">
    <div className="next-heading"><span className="utility-label">NEXT · {path ? 'PATH' : 'SIMULATION'}</span><strong>{path ? '경로 계획' : '시뮬레이션'}</strong></div>
    <p>{path ? '지시 분석 완료. 선택된 영역의 경로를 계획하세요.' : '현재 VLA 3D prediction이 있으면 Path Preview부터 확인하세요. 미리보기는 직접 시작합니다.'}</p>
    <button className="button primary full-width" onClick={onContinue}>{path ? '경로 계획으로 계속' : 'Simulator로 이동'}<Icon name="arrow" size={16} /></button>
  </section>;
}
