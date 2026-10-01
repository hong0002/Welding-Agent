"""Explicit mask intent only; coordinates and arbitrary drawing are never accepted."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class MaskIntent:
    detect: bool = False
    redetect: bool = False

    @classmethod
    def parse(cls, message):
        text = re.sub(r'\s+', '', message.lower())
        if re.search(r"내가.*(?:그린|표시|그릴)|직접.*(?:그릴|표시)|표시한영역|표시한부분|manual|drawn|하지마|하지말|말고|마세요|금지|don't|donot|never|설명|예시|방법|howto|example", text):
            return cls()
        redetect = bool(re.search(r'재검출|재탐지|re-?detect|(?:마스크|영역|용접선).*다시.*(?:찾|검출|탐지|생성|만들)', text))
        detect = redetect or bool(re.search(
            r'(?:마스크|mask).*(?:씌워|생성|만들|찾|검출|탐지|detect|generate|create)|'
            r'용접(?:영역|선|할부분|위치).*(?:찾|검출|탐지|표시|선택)|'
            r'(?:자동|ai로|vlm|auto).*(?:찾|검출|선택|탐지|detect|segment|find)|find.*weld', text))
        return cls(detect, redetect)
