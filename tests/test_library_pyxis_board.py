from pnu_notice_feed.library_pyxis_board import notices_from_pyxis_payload


def test_notices_from_pyxis_payload_extracts_attachments():
    payload = {
        "success": True,
        "data": {
            "list": [
                {
                    "id": 56924,
                    "title": "도서관 보조인력 공개채용 공고",
                    "dateCreated": "2026-06-01 09:06:57",
                    "attachments": [
                        {
                            "logicalName": "채용 공고.hwp",
                            "fileType": "application/haansofthwp",
                            "originalImageUrl": "/attachments/BULLETIN/file-id",
                        }
                    ],
                }
            ]
        },
    }

    notices = notices_from_pyxis_payload(payload, "https://lib.pusan.ac.kr/guide/notice", 10)

    assert len(notices) == 1
    assert notices[0].notice_id == "56924"
    assert notices[0].url == "https://lib.pusan.ac.kr/guide/notice/56924"
    assert notices[0].published_at == "2026-06-01"
    assert notices[0].attachments[0].name == "채용 공고.hwp"
    assert notices[0].attachments[0].url == "https://lib.pusan.ac.kr/attachments/BULLETIN/file-id"
