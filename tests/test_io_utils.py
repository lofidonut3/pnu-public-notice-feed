import hashlib
from pnu_notice_feed.archive import write_json_if_changed, document_file_meta


def test_published_bytes_equal_manifest_checksum_including_windows_checkout(tmp_path):
    doc={'title':'부산대 공지','items':[]}
    path=tmp_path/'month.json'
    write_json_if_changed(path,doc,True)
    path.write_bytes(path.read_bytes().replace(b'\n',b'\r\n'))
    write_json_if_changed(path,doc,True)
    assert b'\r\n' not in path.read_bytes()
    assert hashlib.sha256(path.read_bytes()).hexdigest()==document_file_meta(doc,True)['sha256']
