from pnu_notice_feed.legacy_php_board import parse_legacy_php_list


def test_parse_legacy_php_list_extracts_notice_rows():
    html = """
    <form name="formDetail" id="formDetail" method="get" action="?">
      <input type="hidden" name="db" value="supervision"/>
    </form>
    <table>
      <tbody>
        <tr>
          <td class="number">342</td>
          <td class="title left">
            <a href="javascript:goDetail(348)">
              <span class="type"><span class="head">대학원</span></span>
              2026년도 석사우수장학금 신규장학생 선발 안내
              <span class="mobile-info">
                <span>2026-05-26</span>
                <span>권*경</span>
              </span>
            </a>
          </td>
          <td class="date">2026-05-26</td>
        </tr>
      </tbody>
    </table>
    """

    notices = parse_legacy_php_list(
        html,
        "https://me.pusan.ac.kr/new/sub05/sub01_05.php",
    )

    assert len(notices) == 1
    assert notices[0].notice_id == "348"
    assert notices[0].title == "2026년도 석사우수장학금 신규장학생 선발 안내"
    assert notices[0].published_at == "2026-05-26"
    assert notices[0].url == (
        "https://me.pusan.ac.kr/new/sub05/sub01_05.php"
        "?db=supervision&seq=348&page=1&perPage=10&page_mode=view"
    )
