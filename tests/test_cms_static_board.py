from pnu_notice_feed.cms_static_board import (
    ListItem,
    parse_cms_detail,
    parse_cms_list,
    should_fetch_cms_detail,
)


def test_parse_cms_list_extracts_notice_rows():
    html = """
    <table><tbody>
      <tr class="child_1 isnotice">
        <td class="num">공지</td>
        <td class="subject">
          <p class="stitle">
            <a href="?mgr_seq=3&mode=view&mgr_seq=3&board_seq=1509224">
              <strong>짧은 제목...</strong>
            </a>
            <img class="isFileIcon" alt="'긴 제목 전체'의 첨부파일" />
          </p>
        </td>
        <td class="writer">황*수</td>
        <td class="date">2026-06-02</td>
        <td class="cnt">148</td>
      </tr>
    </tbody></table>
    """

    items = parse_cms_list(
        html,
        "https://www.pusan.ac.kr/kor/CMS/Board/PopupBoard.do?mgr_seq=3&mode=list",
    )

    assert len(items) == 1
    assert items[0].notice_id == "1509224"
    assert items[0].title == "긴 제목 전체"
    assert items[0].published_at == "2026-06-02"
    assert items[0].url.endswith("board_seq=1509224")


def test_parse_cms_list_extracts_normal_rows_without_class():
    html = """
    <table><tbody>
      <tr>
        <td class="num">1</td>
        <td class="subject">
          <p class="stitle">
            <a href="?mgr_seq=3&mode=view&mgr_seq=3&board_seq=1509234">
              일반 공지 제목
            </a>
          </p>
        </td>
        <td class="writer">홍*동</td>
        <td class="date">2026-06-02</td>
        <td class="cnt">10</td>
      </tr>
    </tbody></table>
    """

    items = parse_cms_list(
        html,
        "https://www.pusan.ac.kr/kor/CMS/Board/PopupBoard.do?mgr_seq=3&mode=list",
    )

    assert len(items) == 1
    assert items[0].notice_id == "1509234"
    assert items[0].title == "일반 공지 제목"


def test_parse_cms_detail_extracts_title_snippet_and_attachments():
    html = """
    <div class="board-view-title">
      <h4 class="vtitle">공지 상세 제목</h4>
      <div class="vtitle-winfo">작성자 홍*동 작성일자 2026-06-02</div>
    </div>
    <div class="board-view-contents">
      <div id="boardContents">
        <p>첫 문장입니다.</p>
        <p>둘째 문장입니다.</p>
      </div>
    </div>
    <ul class="board-view-filelist">
      <li>
        <a href="/kor/ajx_json/UploadMgr/downloadRun.do?qcode=abc">
          첨부파일.pdf (257KB)
        </a>
      </li>
    </ul>
    """

    detail = parse_cms_detail(html, "https://www.pusan.ac.kr/kor/CMS/Board/PopupBoard.do")

    assert detail.title == "공지 상세 제목"
    assert detail.snippet == "첫 문장입니다. 둘째 문장입니다."
    assert len(detail.attachments) == 1
    assert detail.attachments[0].name == "첨부파일.pdf (257KB)"
    assert detail.attachments[0].type == "pdf"


def test_cms_detail_revalidation_fetches_new_notice():
    item = _list_item("1509234", "새 공지", "2026-06-02")

    assert should_fetch_cms_detail(
        item,
        "pnu-main-notice:1509234",
        cached_item=None,
        checked_at="2026-06-04T12:00:00+09:00",
        item_index=0,
    )


def test_cms_detail_revalidation_fetches_when_list_metadata_changed():
    item = _list_item("1509234", "수정된 제목", "2026-06-02")
    cached_item = _cached_item("pnu-main-notice:1509234", "이전 제목", "2026-06-02")

    assert should_fetch_cms_detail(
        item,
        "pnu-main-notice:1509234",
        cached_item=cached_item,
        checked_at="2026-06-04T12:00:00+09:00",
        item_index=20,
    )


def test_cms_detail_revalidation_fetches_top_item_when_ttl_expired():
    item = _list_item("1509234", "공지", "2026-06-02")
    missing_timestamp_item = _cached_item(
        "pnu-main-notice:1509234",
        "공지",
        "2026-06-02",
        detail_checked_at=None,
    )
    cached_item = _cached_item(
        "pnu-main-notice:1509234",
        "공지",
        "2026-06-02",
        detail_checked_at="2026-06-04T00:00:00+09:00",
    )

    assert should_fetch_cms_detail(
        item,
        "pnu-main-notice:1509234",
        cached_item=cached_item,
        checked_at="2026-06-04T12:00:00+09:00",
        item_index=0,
    )
    assert should_fetch_cms_detail(
        item,
        "pnu-main-notice:1509234",
        cached_item=missing_timestamp_item,
        checked_at="2026-06-04T12:00:00+09:00",
        item_index=0,
    )


def test_cms_detail_revalidation_skips_fresh_top_item_and_old_window_item():
    item = _list_item("1509234", "공지", "2026-06-02")
    fresh_cached_item = _cached_item(
        "pnu-main-notice:1509234",
        "공지",
        "2026-06-02",
        detail_checked_at="2026-06-04T06:00:00+09:00",
    )
    stale_cached_item = _cached_item(
        "pnu-main-notice:1509234",
        "공지",
        "2026-06-02",
        detail_checked_at="2026-06-03T00:00:00+09:00",
    )

    assert not should_fetch_cms_detail(
        item,
        "pnu-main-notice:1509234",
        cached_item=fresh_cached_item,
        checked_at="2026-06-04T12:00:00+09:00",
        item_index=0,
    )
    assert not should_fetch_cms_detail(
        item,
        "pnu-main-notice:1509234",
        cached_item=stale_cached_item,
        checked_at="2026-06-04T12:00:00+09:00",
        item_index=10,
    )


def _list_item(suffix: str, title: str, published_at: str | None) -> ListItem:
    return ListItem(
        notice_id=suffix,
        title=title,
        url=f"https://www.pusan.ac.kr/notice/{suffix}",
        published_at=published_at,
    )


def _cached_item(
    notice_id: str,
    title: str,
    published_at: str | None,
    detail_checked_at: str | None = "2026-06-04T06:00:00+09:00",
) -> dict:
    pnu = {
        "published_at": published_at,
        "content_hash": "cached-hash",
    }
    if detail_checked_at:
        pnu = {**pnu, "detail_checked_at": detail_checked_at}
    return {
        "id": notice_id,
        "title": title,
        "_pnu": pnu,
    }
