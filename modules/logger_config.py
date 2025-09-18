import logging
import os
from logging import Logger


def setup_logger(log_file_path: str, level: int = logging.INFO) -> Logger:
    """配置并返回项目 Logger。重复调用时避免重复添加 Handler。

    Args:
        log_file_path: 日志文件路径（可相对，可绝对）。
        level: 日志级别，默认 INFO。
    """
    logger = logging.getLogger("audionote")
    logger.setLevel(level)

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出
    if log_file_path:
        os.makedirs(os.path.dirname(os.path.abspath(log_file_path)) or ".", exist_ok=True)
        file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


