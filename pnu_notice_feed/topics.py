from __future__ import annotations

import re
import unicodedata

SOURCE_CATEGORY_TOPICS = {
    "academic_notice": ["academic"],
    "academic_unit_career_notice": ["career"],
    "academic_unit_class_notice": ["course"],
    "academic_unit_graduation_notice": ["graduation"],
    "academic_unit_graduate_notice": ["graduate"],
    "academic_unit_scholarship_notice": ["scholarship"],
    "academic_unit_undergraduate_notice": ["undergraduate"],
    "campus_service_notice": ["campus_service"],
    "career_notice": ["career"],
    "dormitory_notice": ["dormitory"],
    "health_notice": ["health"],
    "international_notice": ["international"],
    "language_education_notice": ["language"],
    "learning_platform_notice": ["learning_platform"],
    "library_notice": ["library"],
    "recruitment_notice": ["recruitment", "career"],
    "research_notice": ["research"],
    "scholarship_notice": ["scholarship"],
    "student_support_notice": ["student_support"],
    "university_notice": ["academic"],
    "university_project_notice": ["campus_service"],
}

TAG_TOPICS = {
    "academic": "academic",
    "career": "career",
    "dormitory": "dormitory",
    "employment": "recruitment",
    "health": "health",
    "international": "international",
    "library": "library",
    "recruitment": "recruitment",
    "research": "research",
    "scholarship": "scholarship",
    "student_support": "student_support",
}

TITLE_TOPIC_PATTERNS = [
    ("scholarship", r"장학|학자금|국가근로|국가장학|근로장학|주거안정장학"),
    ("recruitment", r"채용|추천채용|교원채용|직원채용|인재모집"),
    ("career", r"취업|인턴|현장실습|일자리|역량강화|BUFF"),
    ("contest", r"공모전|공모|경진대회|대회|해커톤|아이디어톤"),
    ("course", r"수강|수업|강의|계절학기|폐강|성적|시험|이수면제"),
    ("graduation", r"졸업|학위청구|논문|외국어시험"),
    ("graduate", r"대학원|석사|박사"),
    ("undergraduate", r"학부"),
    ("international", r"국제|교환학생|유학생|해외|파견"),
    ("dormitory", r"생활원|기숙사|입사|퇴사"),
    ("library", r"도서관|자료실|학술정보"),
    ("health", r"보건|건강|진료|예방접종|감염"),
    ("student_support", r"상담|인권|장애학생|성평등|폭력예방"),
    ("research", r"연구|산학|과제|학술"),
    ("startup", r"창업|스타트업"),
    ("tuition", r"등록금|등록"),
    ("academic_records", r"학적|휴학|복학|전과|재입학"),
    ("campus_service", r"주차|시설|시스템|서비스|앱"),
]


def infer_topics(
    title: str | None,
    source_category: str | None,
    tags: list[str] | None = None,
) -> list[str]:
    topics: list[str] = []
    for topic in SOURCE_CATEGORY_TOPICS.get(source_category or "", []):
        topics = append_unique(topics, topic)

    for tag in tags or []:
        topic = TAG_TOPICS.get(str(tag))
        if topic:
            topics = append_unique(topics, topic)

    normalized_title = normalize_title(title)
    for topic, pattern in TITLE_TOPIC_PATTERNS:
        if re.search(pattern, normalized_title):
            topics = append_unique(topics, topic)

    return topics


def normalize_title(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def append_unique(values: list[str], value: str) -> list[str]:
    if value in values:
        return values
    return [*values, value]
