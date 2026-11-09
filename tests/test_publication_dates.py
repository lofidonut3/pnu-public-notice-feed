"""Regression cases captured from official K2Web date cells on 2026-11-09."""
import pytest
from pnu_notice_feed.html_dates import publication_date
from pnu_notice_feed.k2web_board import parse_k2web_list


@pytest.mark.parametrize('title,actual', [
    ('[졸업] 2027년 2월 졸업요건 서류 제출 안내: ~2027.1.8.', '2023.12.12'),
    ('응용화학공학부 콜로키움 안내(2026/11/25) 새글', '2026.11.04'),
])
def test_title_deadline_does_not_override_publication_cell(title, actual):
    row = f'<tr><td class="td-title"><a href="/bbs/cse/1/1388562/artclView.do">{title}</a></td><td class="td-date">{actual}</td></tr>'
    notice = parse_k2web_list(row, 'https://cse.pusan.ac.kr/')[0]
    assert notice.published_at == actual.replace('.', '-')
    assert not notice.title.endswith('새글')


def test_unknown_date_is_not_invented_from_title():
    assert publication_date('<td><a>신청 마감 2027.1.8.</a></td>') is None
    assert publication_date('<td>2026.02.30</td>') is None


def test_unclassified_legacy_date_cell_remains_supported():
    assert publication_date('<td><a>마감 2027.1.8.</a></td><td>2026.11.04</td>') == '2026-11-04'
