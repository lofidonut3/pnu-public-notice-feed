from pnu_notice_feed.duplicates import build_duplicates


def test_build_duplicates_groups_same_notice_metadata():
    generated_at = "2026-06-05T12:00:00+09:00"
    main_item = _item(
        item_id="pnu-main-notice:1509245",
        source_id="pnu-main-notice",
        title="[장학]한국농어촌희망재단 2026학년도 2학기 청년창업농장학금 선발 안내",
        published_at="2026-06-04",
        attachments=[
            "[붙임]3. 2026년 청년창업농장학금 선발안내-최종.pdf (2MB)",
        ],
    )
    onestop_item = _item(
        item_id="pnu-onestop-notices:681",
        source_id="pnu-onestop-notices",
        title="한국농어촌희망재단 2026학년도 2학기 청년창업농장학금 선발 안내",
        published_at="2026-06-04",
        attachments=[
            "[붙임]3. 2026년 청년창업농장학금 선발안내-최종.pdf",
        ],
    )

    duplicates = build_duplicates([main_item, onestop_item], generated_at)

    assert duplicates["schema_version"] == "0.1"
    assert duplicates["generated_at"] == generated_at
    assert duplicates["item_count"] == 2
    assert duplicates["group_count"] == 1
    assert duplicates["policy"] == {
        "scope": "metadata_only_high_confidence",
        "raw_items_preserved": True,
        "full_body_fetched_for_dedupe": False,
        "false_positive_policy": "avoid_suppressing_distinct_notices",
    }
    group = duplicates["groups"][0]
    assert group["relationship"] == "same_notice"
    assert group["confidence"] == "high"
    assert group["consumer_action"] == "dedupe_notifications"
    assert group["item_ids"] == [
        "pnu-main-notice:1509245",
        "pnu-onestop-notices:681",
    ]
    assert group["source_ids"] == [
        "pnu-main-notice",
        "pnu-onestop-notices",
    ]
    assert group["published_dates"] == ["2026-06-04"]
    assert group["evidence"] == [
        "cross_source",
        "same_normalized_title",
        "same_published_date",
        "shared_attachment_names",
    ]


def test_build_duplicates_does_not_merge_sequence_notices():
    generated_at = "2026-06-05T12:00:00+09:00"
    first_round = _item(
        item_id="pnu-onestop-notices:1",
        source_id="pnu-onestop-notices",
        title="2026학년도 여름계절 및 도약수업 1차 폐강강좌 통보 및 수강정정 안내",
        published_at="2026-06-02",
        attachments=["붙임1. 2026학년도 여름계절 및 도약수업 1차 폐강강좌 통보.hwp"],
    )
    final_round = _item(
        item_id="pnu-main-notice:2",
        source_id="pnu-main-notice",
        title="2026학년도 여름계절 및 도약수업 2차(최종) 폐강강좌 통보 및 수강정정 안내",
        published_at="2026-06-02",
        attachments=["붙임1. 2026학년도 여름계절 및 도약수업 2차 폐강강좌 통보.hwp"],
    )

    duplicates = build_duplicates([first_round, final_round], generated_at)

    assert duplicates["group_count"] == 0
    assert duplicates["groups"] == []


def test_build_duplicates_skips_recruitment_and_dorm_title_only_matches():
    generated_at = "2026-06-05T12:00:00+09:00"
    recruitment_a = _item(
        item_id="pnu-job-recruit-general:1",
        source_id="pnu-job-recruit-general",
        title="추천채용 안내",
        published_at="2026-06-04",
        attachments=[],
    )
    recruitment_b = _item(
        item_id="pnu-job-recruit-recommendation:2",
        source_id="pnu-job-recruit-recommendation",
        title="추천채용 안내",
        published_at="2026-06-04",
        attachments=[],
    )
    dorm_busan = _item(
        item_id="pnu-dorm-busan-notices:1",
        source_id="pnu-dorm-busan-notices",
        title="방역 및 소독 안내",
        published_at="2026-06-04",
        attachments=[],
    )
    dorm_yangsan = _item(
        item_id="pnu-dorm-yangsan-notices:2",
        source_id="pnu-dorm-yangsan-notices",
        title="방역 및 소독 안내",
        published_at="2026-06-04",
        attachments=[],
    )

    duplicates = build_duplicates(
        [recruitment_a, recruitment_b, dorm_busan, dorm_yangsan],
        generated_at,
    )

    assert duplicates["group_count"] == 0
    assert duplicates["groups"] == []


def _item(
    item_id: str,
    source_id: str,
    title: str,
    published_at: str,
    attachments: list[str],
) -> dict:
    return {
        "id": item_id,
        "url": f"https://example.test/{item_id}",
        "title": title,
        "content_text": "metadata only",
        "summary": None,
        "date_published": f"{published_at}T00:00:00+09:00",
        "_pnu": {
            "source_id": source_id,
            "source_name": source_id,
            "published_at": published_at,
            "fetched_at": "2026-06-05T12:00:00+09:00",
            "snippet": None,
            "content_access": {
                "detail_url": f"https://example.test/{item_id}",
                "requires_login": False,
                "content_mirrored": False,
                "attachments_mirrored": False,
            },
            "attachments": [
                {
                    "name": attachment,
                    "url": f"https://example.test/{attachment}",
                    "download_url": f"https://example.test/{attachment}",
                    "type": None,
                    "media_type": None,
                    "file_extension": attachment.rsplit(".", 1)[-1],
                }
                for attachment in attachments
            ],
            "tags": [],
            "content_hash": item_id,
        },
    }
