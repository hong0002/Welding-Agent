import type { Stroke } from './types';

/** Rasterize at original resolution. Display opacity and stage scaling never enter this path. */
export async function exportBinaryMask(width: number, height: number, strokes: Stroke[], baseMaskUrl?: string | null): Promise<Blob> {
  const canvas = document.createElement('canvas');
  canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('Canvas를 초기화하지 못했습니다.');
  if (baseMaskUrl) ctx.drawImage(await loadMaskLayer(baseMaskUrl, width, height), 0, 0);
  for (const stroke of strokes) {
    ctx.globalCompositeOperation = stroke.tool === 'eraser' ? 'destination-out' : 'source-over';
    ctx.strokeStyle = '#fff'; ctx.fillStyle = '#fff';
    ctx.lineWidth = stroke.size; ctx.lineJoin = 'round'; ctx.lineCap = 'round';
    ctx.beginPath();
    if (stroke.points.length === 2) {
      ctx.arc(stroke.points[0], stroke.points[1], stroke.size / 2, 0, Math.PI * 2); ctx.fill();
    } else {
      ctx.moveTo(stroke.points[0], stroke.points[1]);
      for (let i = 2; i < stroke.points.length; i += 2) ctx.lineTo(stroke.points[i], stroke.points[i + 1]);
      ctx.stroke();
    }
  }
  const image = ctx.getImageData(0, 0, width, height);
  let selected = 0;
  for (let i = 0; i < image.data.length; i += 4) {
    const value = image.data[i + 3] >= 128 ? 255 : 0;
    image.data[i] = image.data[i + 1] = image.data[i + 2] = value;
    image.data[i + 3] = 255;
    selected += value === 255 ? 1 : 0;
  }
  if (!selected) throw new Error('마스크가 비어 있습니다. 용접할 영역을 먼저 그려주세요.');
  ctx.putImageData(image, 0, 0);
  return new Promise((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('마스크 PNG 생성 실패')), 'image/png'));
}

/** Convert a server binary PNG into foreground alpha. Black background MUST be transparent. */
export async function loadMaskLayer(url: string, width: number, height: number): Promise<HTMLCanvasElement> {
  const response = await fetch(url, { signal: AbortSignal.timeout(20_000) });
  if (!response.ok) throw new Error('마스크 이미지를 불러오지 못했습니다.');
  const bitmap = await createImageBitmap(await response.blob());
  try {
    if (bitmap.width !== width || bitmap.height !== height) throw new Error('마스크 해상도가 장면과 다릅니다.');
    const canvas = document.createElement('canvas'); canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
    ctx.drawImage(bitmap, 0, 0);
    const image = ctx.getImageData(0, 0, width, height);
    for (let i = 0; i < image.data.length; i += 4) {
      const value = image.data[i];
      if ((value !== 0 && value !== 255) || image.data[i + 1] !== value || image.data[i + 2] !== value || image.data[i + 3] !== 255)
        throw new Error('서버 마스크가 0/255 바이너리 형식이 아닙니다.');
      image.data[i] = 255; image.data[i + 1] = 75; image.data[i + 2] = 96; image.data[i + 3] = value;
    }
    ctx.putImageData(image, 0, 0);
    return canvas;
  } finally { bitmap.close(); }
}

/** Synthetic plate image for trying the full workflow without an external dataset. */
export async function createDemoScene(): Promise<Blob> {
  const canvas = document.createElement('canvas'); canvas.width = 1280; canvas.height = 720;
  const ctx = canvas.getContext('2d')!;
  ctx.fillStyle = '#293237'; ctx.fillRect(0, 0, 1280, 720);
  const plate = ctx.createLinearGradient(0, 100, 1000, 650);
  plate.addColorStop(0, '#919b9e'); plate.addColorStop(0.48, '#c0c5c3'); plate.addColorStop(1, '#758084');
  ctx.shadowColor = '#0008'; ctx.shadowBlur = 30;
  ctx.fillStyle = plate; ctx.fillRect(95, 98, 1090, 246); ctx.fillRect(95, 356, 1090, 266);
  ctx.shadowBlur = 0;
  for (let y = 102; y < 620; y += 4) {
    if (y > 342 && y < 360) continue;
    ctx.strokeStyle = y % 8 === 0 ? '#ffffff10' : '#0000000a';
    ctx.beginPath(); ctx.moveTo(97, y); ctx.lineTo(1183, y); ctx.stroke();
  }
  ctx.strokeStyle = '#1c252b'; ctx.lineWidth = 8;
  ctx.beginPath(); ctx.moveTo(98, 349); ctx.lineTo(1182, 349); ctx.stroke();
  for (const x of [127, 1153]) for (const y of [130, 590]) {
    ctx.beginPath(); ctx.arc(x, y, 10, 0, Math.PI * 2); ctx.fillStyle = '#424e51'; ctx.fill();
    ctx.strokeStyle = '#d3d9d6'; ctx.lineWidth = 2; ctx.stroke();
  }
  ctx.fillStyle = '#263737'; ctx.font = '18px monospace'; ctx.fillText('PLATE A  /  SYNTHETIC SCENE', 156, 160);
  ctx.fillText('PLATE B', 156, 584);
  ctx.fillStyle = '#abbab8'; ctx.font = '15px monospace'; ctx.fillText('DEMO 01  ·  1280 × 720 RGB', 95, 673);
  return new Promise((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('샘플 이미지 생성 실패')), 'image/png'));
}
