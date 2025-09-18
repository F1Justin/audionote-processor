from typing import Optional

try:
    from opencc import OpenCC
    _converter: Optional[OpenCC] = OpenCC("t2s")
except Exception:
    _converter = None


def to_simplified(text: str) -> str:
    """将繁体转换为简体。若转换器不可用，原样返回。"""
    if not text:
        return text
    if _converter is None:
        return text
    try:
        return _converter.convert(text)
    except Exception:
        return text


