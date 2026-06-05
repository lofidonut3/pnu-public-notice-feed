from pnu_notice_feed.k2web_board import parse_k2web_list


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

