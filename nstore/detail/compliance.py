"""상세페이지 카피 검사.

- 금지·주의 표현 (config/title_rules.yaml 과 같은 규칙)
- 사실 자료에 없는 숫자 (AI가 만들어낸 규격·수치 잡기)
- 의료기기: 심의 받은 문구에 없는 문장
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..master import squash
from .schema import Facts, Plan

LEVEL_ERROR = "오류"
LEVEL_WARNING = "주의"

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_SENTENCE_SPLIT = re.compile(r"[.!?\n]+")
MEDICAL_VALUES = {"Y", "y", "예", "O", "o", "의료기기", "TRUE", "True", "1"}


@dataclass
class Finding:
    section_id: str
    level: str
    message: str

    def __str__(self) -> str:
        return f"[{self.section_id}] {self.level}: {self.message}"


def is_medical(product: dict) -> bool:
    return str(product.get("의료기기여부", "")).strip() in MEDICAL_VALUES


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)}


def _texts(section) -> list[str]:
    texts = [section.eyebrow, section.headline, section.body]
    for item in section.items:
        # 사용 순서의 'STEP 1' 같은 번호는 검사하지 않음
        texts.append(item.text if section.type == "usage" else f"{item.title} {item.text}")
        if section.type == "usage":
            texts.append(re.sub(r"(?i)step\s*\d+", "", item.title))
    return [t for t in texts if t]


def check_plan(plan: Plan, facts: Facts | None, rules: dict, product: dict, approved: str) -> list[Finding]:
    findings: list[Finding] = []
    known_numbers: set[str] = set()
    if facts:
        known_numbers = _numbers(facts.model_dump_json()) | _numbers(" ".join(map(str, product.values())))
    approved_compact = squash(approved)
    medical = is_medical(product)

    if medical and not approved:
        findings.append(Finding("전체", LEVEL_ERROR, "의료기기 상품 — 광고 자율심의 전 초안입니다. 심의 문구(approved_copy.txt)를 넣기 전에는 게시하지 마세요."))

    for section in plan.sections:
        for text in _texts(section):
            compact = squash(text)
            for phrase in rules.get("error_phrases", []):
                if squash(str(phrase)) in compact:
                    findings.append(Finding(section.id, LEVEL_ERROR, f"금지 문구 '{phrase}'"))
            for phrase in rules.get("warning_phrases", []):
                if squash(str(phrase)) in compact:
                    findings.append(Finding(section.id, LEVEL_WARNING, f"확인 필요 표현 '{phrase}'"))
            if facts:
                for number in sorted(_numbers(text) - known_numbers):
                    findings.append(Finding(section.id, LEVEL_WARNING, f"자료에 없는 숫자 '{number}' — 사실인지 확인하세요"))
            if medical and approved:
                for sentence in _SENTENCE_SPLIT.split(text):
                    s = squash(sentence)
                    if len(s) >= 6 and s not in approved_compact:
                        findings.append(Finding(section.id, LEVEL_WARNING, f"심의 문구에 없는 문장: {sentence.strip()[:40]}"))
    return findings
