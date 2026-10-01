// UX preflight only. Backend intent, ownership and approval gates remain authoritative.
export function maskIntent(message:string) {
  const text=message.toLowerCase().replace(/\s+/g,'');
  if (/내가.*(?:그린|표시|그릴)|직접.*(?:그릴|표시)|표시한영역|표시한부분|manual|drawn|하지마|하지말|말고|마세요|금지|don't|donot|never|설명|예시|방법|howto|example/.test(text)) return {detect:false,redetect:false};
  const redetect=/재검출|재탐지|re-?detect|(?:마스크|영역|용접선).*다시.*(?:찾|검출|탐지|생성|만들)/.test(text);
  const detect=redetect||/(?:마스크|mask).*(?:씌워|생성|만들|찾|검출|탐지|detect|generate|create)|용접(?:영역|선|할부분|위치).*(?:찾|검출|탐지|표시|선택)|(?:자동|ai로|vlm|auto).*(?:찾|검출|선택|탐지|detect|segment|find)|find.*weld/.test(text);
  return {detect,redetect};
}

export function sceneLoadIntent(message:string) {
  if (!/불러|로드|\bload\b|\bopen\b/i.test(message)||/하지마|하지말|말고|마세요|금지|설명|방법|don't|do not|never|how to/i.test(message))return false;
  const ids=message.match(/\b[A-Za-z][A-Za-z0-9_]{1,127}\b/g)??[];
  return ids.filter(value=>value.includes('_')&&/\d/.test(value)).length===1;
}
