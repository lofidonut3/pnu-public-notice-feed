import pytest

from pnu_notice_feed.k2web_board import fetch_k2web_board, parse_k2web_list
from pnu_notice_feed.types import Source


def test_parse_k2web_list_extracts_rows_and_deduplicates_fixed_notice():
    html = """
    <table>
      <tbody>
        <tr>
          <td class="td-num">공지</td>
          <td class="td-subject">
            <a href="/bbs/international/2081/1442154/artclView.do">
              Notice title
            </a>
          </td>
          <td class="td-date">2026.06.01</td>
        </tr>
        <tr>
          <td class="td-num">1</td>
          <td class="td-subject">
            <a href="/bbs/international/2081/1442154/artclView.do">
              Notice title duplicate
            </a>
          </td>
          <td class="td-date">2026.06.01</td>
        </tr>
        <tr>
          <td class="td-num">2</td>
          <td class="td-subject">
            <a href="/bbs/international/2081/1442462/artclView.do">
              New notice
            </a>
          </td>
          <td class="td-date">2026.06.04</td>
        </tr>
      </tbody>
    </table>
    """

    notices = parse_k2web_list(html, "https://international.pusan.ac.kr/international/15224/subview.do")

    assert [notice.notice_id for notice in notices] == ["1442154", "1442462"]
    assert notices[0].title == "Notice title"
    assert notices[0].published_at == "2026-06-01"
    assert notices[0].url == "https://international.pusan.ac.kr/bbs/international/2081/1442154/artclView.do"
    assert notices[0].is_pinned is True
    assert notices[1].is_pinned is False


def test_fetch_k2web_board_paginates_until_non_pinned_known_id(monkeypatch):
    first_page = """
    <form method="post" action="/bbs/example/1/artclList.do">
      <input name="layout" value="layout-token">
    </form>
    <table>
      <tr class="notice"><td><span class="notice-title">공지</span></td>
        <td><a href="/bbs/example/1/900/artclView.do">Pinned known</a></td></tr>
      <tr><td>1</td><td><a href="/bbs/example/1/105/artclView.do">New item</a></td></tr>
    </table>
    """
    second_page = """
    <table>
      <tr class="notice"><td><span class="notice-title">공지</span></td>
        <td><a href="/bbs/example/1/900/artclView.do">Pinned known</a></td></tr>
      <tr><td>2</td><td><a href="/bbs/example/1/100/artclView.do">Known boundary</a></td></tr>
    </table>
    """
    calls = []

    def fake_fetch(url, form=None):
        calls.append((url, form))
        return first_page if form is None else second_page

    monkeypatch.setattr("pnu_notice_feed.k2web_board.fetch_text", fake_fetch)
    source = Source(
        id="example",
        name="Example",
        adapter="k2web-board",
        entry_url="https://example.test/example/1/subview.do",
    )

    notices = fetch_k2web_board(
        source,
        limit=80,
        known_notice_ids={"example:900", "example:100"},
        max_catchup_pages=3,
    )

    assert [notice.notice_id for notice in notices] == [
        "example:900",
        "example:105",
        "example:100",
    ]
    assert calls[1] == (
        "https://example.test/bbs/example/1/artclList.do",
        {"page": "2", "layout": "layout-token"},
    )


def test_fetch_k2web_board_fails_closed_when_known_boundary_is_missing(monkeypatch):
    page = """
    <form method="post" action="/bbs/example/1/artclList.do"></form>
    <table><tr><td>1</td><td>
      <a href="/bbs/example/1/105/artclView.do">New item</a>
    </td></tr></table>
    """
    monkeypatch.setattr(
        "pnu_notice_feed.k2web_board.fetch_text",
        lambda _url, form=None: page,
    )
    source = Source(
        id="example",
        name="Example",
        adapter="k2web-board",
        entry_url="https://example.test/example/1/subview.do",
    )

    with pytest.raises(RuntimeError, match="boundary was not found"):
        fetch_k2web_board(
            source,
            limit=80,
            known_notice_ids={"example:100"},
            max_catchup_pages=2,
        )
