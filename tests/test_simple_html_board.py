from pnu_notice_feed.simple_html_board import (
    parse_plato_ubboard_list,
    parse_simple_html_list,
)


def test_parse_simple_html_list_extracts_boardview_rows():
    html = """
    <table><tbody>
      <tr>
        <th scope="row">42</th>
        <td class="text-left">
          <a href="/sanhak/boardview/4/54">산학협력단 공지</a>
        </td>
        <td>관리자</td>
        <td>2026.06.04 15:59</td>
      </tr>
    </tbody></table>
    """

    items = parse_simple_html_list(html, "https://sanhak.pusan.ac.kr/sanhak/board/4")

    assert len(items) == 1
    assert items[0].notice_id == "4-54"
    assert items[0].title == "산학협력단 공지"
    assert items[0].url == "https://sanhak.pusan.ac.kr/sanhak/boardview/4/54"
    assert items[0].published_at == "2026-06-04"


def test_parse_plato_ubboard_list_extracts_public_rows():
    html = """
    <table><tbody>
      <tr>
        <td class="tcenter">공지</td>
        <td>
          <a href="https://plato.pusan.ac.kr/mod/ubboard/article.php?id=1&amp;bwid=2446603">
            PLATO 공지
          </a>
        </td>
        <td class="tcenter">교수학습부</td>
        <td class="tcenter">2026-06-01</td>
      </tr>
    </tbody></table>
    """

    items = parse_plato_ubboard_list(
        html,
        "https://plato.pusan.ac.kr/mod/ubboard/view.php?id=1",
    )

    assert len(items) == 1
    assert items[0].notice_id == "2446603"
    assert items[0].title == "PLATO 공지"
    assert items[0].url == (
        "https://plato.pusan.ac.kr/mod/ubboard/article.php?id=1&bwid=2446603"
    )
    assert items[0].published_at == "2026-06-01"
