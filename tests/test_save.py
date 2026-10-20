import io
import zipfile

import pytest

from agent import save

HEADER = b"SAV0103a1b2c3d400001234\n"
TEXT = b'date=1836.1.1\nplayed_country={ name="GBR" }\n'


def write(tmp_path, data):
    p = tmp_path / "test.v3"
    p.write_bytes(data)
    return str(p)


def zipped(gamestate, meta=b"date=1836.1.1\n"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("meta", meta)
        z.writestr("gamestate", gamestate)
    return buf.getvalue()


def test_plain_text_save(tmp_path):
    d = save.load(write(tmp_path, HEADER + TEXT))
    assert d["date"] == "1836.1.1"
    assert d["played_country"] == {"name": "GBR"}


def test_zipped_text_save(tmp_path):
    raw = save.read_raw(write(tmp_path, HEADER + zipped(TEXT)))
    assert raw.header.startswith("SAV")
    assert raw.meta.startswith("date=")
    assert "played_country" in raw.gamestate


def test_binary_save_rejected_with_reason(tmp_path):
    binary = bytes([0x01, 0x00, 0x03, 0x00, 0x0c, 0x00]) * 500
    with pytest.raises(save.SaveFormatError, match="debug_mode"):
        save.read_raw(write(tmp_path, HEADER + zipped(binary)))


def test_not_a_save(tmp_path):
    with pytest.raises(save.SaveFormatError, match="SAV"):
        save.read_raw(write(tmp_path, b"hello"))
