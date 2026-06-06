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
