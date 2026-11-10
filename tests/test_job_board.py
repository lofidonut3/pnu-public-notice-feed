from pnu_notice_feed import job_board
from pnu_notice_feed.agent_views import preview_item
from pnu_notice_feed.archive import build_archive_documents
from pnu_notice_feed.generator import compact_state_item, notice_to_feed_item
from pnu_notice_feed.job_board import parse_job_notice_list, parse_job_recruit_list
from pnu_notice_feed.types import Source


def test_parse_job_notice_list_extracts_title_url_and_date():
    html = """
    <ul data-role="table">
      <li class="tbody">
        <span class="subject">
          <a class="new" href="/ko/notice/notice/view/204016?p=1">
            <i class="fa fa-picture-o"></i>대학생 ESG아카데미 모집
          </a>
        </span>
        <span class="reg_date">
          <time datetime="2026-06-05T09:36:16+09:00">2026-06-05</time>
        </span>
      </li>
    </ul>
    """

    notices = parse_job_notice_list(html, "https://job.pusan.ac.kr/ko/notice")

    assert len(notices) == 1
    assert notices[0].notice_id == "204016"
    assert notices[0].title == "대학생 ESG아카데미 모집"
    assert notices[0].published_at == "2026-06-05"
    assert notices[0].url == "https://job.pusan.ac.kr/ko/notice/notice/view/204016?p=1"


def test_parse_job_recruit_list_keeps_company_and_deadline_in_snippet():
    html = """
    <li class="tbody">
      <span class="co"><div class="tit">전북연구원</div></span>
      <span class="subject">
        <div class="tit">
          <a href="/ko/recruit/board/view/117375">전북연구원 직원 채용 공고</a>
        </div>
        <div class="sub_tit"><span class="recruit_type contractor">계약직</span></div>
      </span>
      <span class="side"><span class="end_date">2026-06-15<br>14:00</span></span>
    </li>
    """

    notices = parse_job_recruit_list(html, "https://job.pusan.ac.kr/ko/recruit/board")

    assert len(notices) == 1
    assert notices[0].notice_id == "117375"
    assert notices[0].title == "전북연구원 직원 채용 공고"
    assert notices[0].published_at is None
    assert notices[0].snippet == "회사: 전북연구원 / 유형: 계약직 / 마감: 2026-06-15 14:00"


def test_home_recruit_cards_get_calendar_links_without_new_archive_events(monkeypatch):
    home = "https://job.pusan.ac.kr/"
    source = Source("pnu-job-recruit-internship", "인턴십", "job-recruit-html-board", home)
    calendar = "/ko/community/calendar/intern"
    first_month = f"{home.rstrip('/')}{calendar}"
    next_month = f"{first_month}/list/2026/12"
    homepage = """
    <a href="/ko/recruit/Intern/view/118523" class="item"><div class="sub">[SNOW] 체험형 인턴</div></a>
    <a href="/ko/recruit/Intern/view/118505" class="item"><div class="sub">와이즐리 인턴</div></a>
    """
    pages = {
        home: homepage,
        first_month: f'<a href="{calendar}/list/2026/12" class="next">다음달</a>',
        next_month: f"""
        <button data-action="apply" data-ridx="118523" data-title="[SNOW] 체험형 인턴"
            data-url="{calendar}/view/118523">SNOW ~23:59</button>
        <button data-action="apply" data-ridx="118505" data-title="다른 회사 인턴"
            data-url="{calendar}/view/118505">다른 회사 ~23:59</button>
        <button data-action="apply" data-ridx="118505" data-title="와이즐리 인턴"
            data-url="//wrong.example{calendar}/view/118505">와이즐리 ~23:59</button>
        <a href="{calendar}/list/2027/01" class="next">다음달</a>
        """,
    }
    fetched_urls = []

    def fetch(url, *, timeout=20):
        fetched_urls.append((url, timeout))
        return pages[url]

    monkeypatch.setattr(job_board, "fetch_text", fetch)
    old = job_board._to_notices(source, job_board.parse_job_home_recruit_list(homepage, home, "Intern"))
    old_time = "2026-11-10T15:00:00+09:00"
    before = {"_pnu": {"generated_at": old_time}, "items": [notice_to_feed_item(n, old_time) for n in old]}
    archive, index = build_archive_documents(before)
    updated = job_board.fetch_job_recruit_board(source, 10)
    assert fetched_urls == [(home, 20), (first_month, 10), (next_month, 10)]
    assert [item.notice_id for item in updated] == [item.notice_id for item in old]
    assert [item.content_hash for item in updated] == [item.content_hash for item in old]
    assert updated[0].url == f"{first_month}/view/118523"
    assert updated[1].url == old[1].url

    now = "2026-11-10T16:00:00+09:00"
    new_items = [notice_to_feed_item(notice, now) for notice in updated]
    after, _ = build_archive_documents({"_pnu": {"generated_at": now}, "items": new_items}, archive, index)
    old_events = {item["notice_id"]: item for item in archive["2026-11"]["events"]}
    new_events = {item["notice_id"]: item for item in after["2026-11"]["events"]}
    assert len(new_events) == len(old_events) == 2
    assert {event["event_id"] for event in new_events.values()} == {event["event_id"] for event in old_events.values()}
    assert new_events[updated[0].notice_id]["url"] == updated[0].url
    unresolved_access = new_items[1]["_pnu"]["content_access"]
    assert unresolved_access["detail_url"] is None
    assert unresolved_access["fallback_url"] == home
    assert unresolved_access["availability"] == "detail_unverified"
    assert new_events[updated[1].notice_id]["content_access"] == unresolved_access
    assert preview_item(new_items[1])["content_access"] == unresolved_access

    def fetch_without_calendar(url, *, timeout=20):
        if url != home:
            raise TimeoutError()
        return homepage

    monkeypatch.setattr(job_board, "fetch_text", fetch_without_calendar)
    cached = {item["id"]: compact_state_item(item) for item in new_items}
    assert job_board.fetch_job_recruit_board(source, 10, cached_items=cached) == updated

