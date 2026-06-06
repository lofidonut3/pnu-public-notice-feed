from pnu_notice_feed.topics import infer_topics


def test_infer_topics_uses_source_category_tags_and_title_keywords():
    topics = infer_topics(
        "2026학년도 2학기 국가장학금 1차 신청 안내",
        "academic_unit_undergraduate_notice",
        ["pnu", "official"],
    )

    assert topics == ["undergraduate", "scholarship"]


def test_infer_topics_deduplicates_category_and_tag_topics():
    topics = infer_topics(
        "취업전략과 인턴십 참여자 모집",
        "career_notice",
        ["career"],
    )

    assert topics == ["career"]


def test_infer_topics_supports_event_and_graduate_admissions_categories():
    assert infer_topics(
        "2026학년도 입학공지",
        "graduate_school_admissions_notice",
        ["graduate_school", "admissions"],
    ) == ["graduate", "admissions"]

    assert infer_topics(
        "학과세미나 개최 안내",
        "academic_unit_event_notice",
        ["event"],
    ) == ["event"]
