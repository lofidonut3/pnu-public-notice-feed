from pnu_notice_feed.job_board import parse_job_notice_list, parse_job_recruit_list


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

