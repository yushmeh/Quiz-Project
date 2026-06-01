# --- ФАЙЛ: utils/logger.py ---
"""
Утилита настройки логирования для всего проекта.

Обеспечивает:
- Единый формат логов с временными метками и уровнями
- Цветной вывод в консоль (для разработки)
- Опциональную запись в файл (для production)
- Фабричную функцию get_logger() для получения именованного логгера в любом модуле

Использование в любом модуле:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Сообщение")
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Final

# ─── Константы ────────────────────────────────────────────────────────────────

# Уровень логирования по умолчанию (можно переопределить через переменную окружения)
DEFAULT_LOG_LEVEL: Final[int] = logging.DEBUG

# Имя корневого логгера проекта (все дочерние логгеры наследуют его настройки)
ROOT_LOGGER_NAME: Final[str] = "taiga_quiz"

# Опциональный файл для записи логов
LOG_FILE_PATH: Final[Path] = Path("logs") / "quiz.log"

# ─── Форматтеры ───────────────────────────────────────────────────────────────

# Формат для файлового логгера (полный)
FILE_FORMAT: Final[str] = (
    "[%(asctime)s] %(levelname)-8s  %(name)s:%(lineno)d  %(message)s"
)

# Формат для консольного вывода (компактный)
CONSOLE_FORMAT: Final[str] = (
    "%(levelname)-8s  %(name)s  │  %(message)s"
)

# Формат даты
DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"


# ─── Цветной форматтер для консоли ───────────────────────────────────────────

class ColoredConsoleFormatter(logging.Formatter):
    """
    Расширение стандартного Formatter: добавляет ANSI-цвета к уровням логирования.
    Делает консольный вывод значительно удобнее для чтения во время разработки.
    """

    # ANSI escape-коды для цветов
    COLORS: dict[int, str] = {
        logging.DEBUG:    "\033[36m",   # Циан
        logging.INFO:     "\033[32m",   # Зелёный
        logging.WARNING:  "\033[33m",   # Жёлтый
        logging.ERROR:    "\033[31m",   # Красный
        logging.CRITICAL: "\033[35m",   # Пурпурный + жирный
    }
    RESET: Final[str] = "\033[0m"
    BOLD:  Final[str] = "\033[1m"

    def format(self, record: logging.LogRecord) -> str:
        """Форматирует запись лога с добавлением ANSI-цветов."""
        color = self.COLORS.get(record.levelno, self.RESET)

        # Цветим levelname
        record.levelname = f"{color}{record.levelname}{self.RESET}"

        # Для CRITICAL добавляем жирный
        if record.levelno == logging.CRITICAL:
            record.msg = f"{self.BOLD}{record.msg}{self.RESET}"

        return super().format(record)


# ─── Флаг: настроен ли корневой логгер ───────────────────────────────────────
_root_logger_configured: bool = False


def _configure_root_logger() -> None:
    """
    Настраивает корневой логгер проекта один раз (идемпотентная функция).

    Добавляет два обработчика:
    1. StreamHandler → цветной вывод в stderr (разработка)
    2. FileHandler   → полный вывод в файл (опционально)
    """
    global _root_logger_configured

    if _root_logger_configured:
        return

    root_logger = logging.getLogger(ROOT_LOGGER_NAME)
    root_logger.setLevel(DEFAULT_LOG_LEVEL)

    # Не передаём логи родительскому (корневому Python) логгеру
    root_logger.propagate = False

    # ── Консольный обработчик ──────────────────────────────────────────────
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(
        ColoredConsoleFormatter(fmt=CONSOLE_FORMAT, datefmt=DATE_FORMAT)
    )
    root_logger.addHandler(console_handler)

    # ── Файловый обработчик (создаём папку logs/, если не существует) ─────
    try:
        LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
        file_handler.setLevel(logging.INFO)  # В файл — только INFO и выше
        file_handler.setFormatter(
            logging.Formatter(fmt=FILE_FORMAT, datefmt=DATE_FORMAT)
        )
        root_logger.addHandler(file_handler)
    except PermissionError:
        # Не прерываем работу, если нет прав на запись логов
        root_logger.warning(
            "Нет прав на создание файла логов: %s. Пишем только в консоль.",
            LOG_FILE_PATH
        )

    _root_logger_configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Возвращает именованный дочерний логгер проекта.

    При первом вызове автоматически настраивает корневой логгер.
    Последующие вызовы просто возвращают логгер из кеша Python.

    Args:
        name: Имя модуля (обычно передаётся __name__)
               Пример: "data.question_provider", "core.quiz_engine"

    Returns:
        Настроенный объект logging.Logger

    Пример:
        logger = get_logger(__name__)
        logger.info("Сервер запущен на порту %d", 8000)
        logger.warning("Показатель тепла критически низкий: %d", 15)
        logger.error("Не удалось загрузить вопросы: %s", str(exc))
    """
    _configure_root_logger()

    # Формируем иерархическое имя: "taiga_quiz.core.quiz_engine"
    if name.startswith(ROOT_LOGGER_NAME):
        full_name = name
    else:
        full_name = f"{ROOT_LOGGER_NAME}.{name}"

    return logging.getLogger(full_name)