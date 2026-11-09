"""Fingerprint the observed public K2Web content container; never mirror it."""
import hashlib
from html.parser import HTMLParser


class BodyParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []
        self.found = False
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if not self.stack:
            if tag != 'div' or not {'viewCont','artclView'} & set(attrs.get('class', '').split()):
                return
            self.found = True
            self.stack = [tag]
            return
        if tag in {'script','style'}:
            self.hidden += 1
        if tag not in {'img','br','hr','input','meta','link','source','wbr'}:
            self.stack.append(tag)
        if tag in {'a','img'}:
            self.parts.append(attrs.get('href') or attrs.get('src') or '')

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack:
                popped = self.stack.pop()
                if popped in {'script','style'}:
                    self.hidden = max(0, self.hidden-1)
                if popped == tag:
                    break

    def handle_data(self, data):
        if self.stack and not self.hidden:
            self.parts.append(data)


def body_fingerprint(page):
    parser = BodyParser()
    parser.feed(page)
    if not parser.found:
        raise ValueError('official public detail content container was not found')
    text = ' '.join(' '.join(parser.parts).split())
    if not text:
        raise ValueError('official public detail content container was empty')
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def is_detail_baseline_only(previous, current):
    old = previous.get('_pnu', {})
    new = current.get('_pnu', {})
    return bool(not old.get('detail_content_hash') and new.get('detail_content_hash')
        and previous.get('title') == current.get('title')
        and previous.get('url') == current.get('url')
        and old.get('published_at') == new.get('published_at'))
