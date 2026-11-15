"""An original stored on one machine is found on another by its content-hash name."""

from __future__ import annotations

from app.core.config import get_settings
from app.ingest.intake import blob_file


def test_a_windows_blob_path_is_found_under_this_blob_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "blob_dir", tmp_path)
    f = tmp_path / "default" / "ab" / "abcdef.docx"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    stored = r"D:\laptop\company knowledge engine\data\blobs\default\ab\abcdef.docx"
    assert blob_file(stored) == f
    assert blob_file("/srv/old/blobs/default/ab/abcdef.docx") == f  # another POSIX machine
    assert blob_file(str(f)) == f  # stored here: used as is
    assert blob_file(r"D:\x\default\ab\missing.docx") is None
    assert blob_file(None) is None and blob_file("short.docx") is None
