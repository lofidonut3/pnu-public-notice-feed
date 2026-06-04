from pnu_notice_feed.cms_static_board import parse_cms_detail, parse_cms_list


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

