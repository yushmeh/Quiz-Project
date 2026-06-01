# --- ФАЙЛ: main.py ---
"""
Точка входа приложения "Выжить в Тайге".

Обязанности этого модуля:
- Создать и настроить FastAPI-приложение
- Подключить статические файлы и маршруты
- Инициализировать зависимости (QuestionProvider, SessionStore)
- Запустить Uvicorn-сервер

Принцип: этот файл — только конфигурация и запуск.
Никакой бизнес-логики здесь нет.
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.quiz_engine import SessionStore
from data.question_provider import QuestionProvider
from utils.logger import get_logger
from web.router import create_router

# ─── Настройка логгера для точки входа ───────────────────────────────────────
logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Создание FastAPI-приложения
# ─────────────────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """
    Фабрика FastAPI-приложения.

    Использование фабрики (а не глобального `app`) позволяет:
    - Легко тестировать (создаём свежий экземпляр в каждом тесте)
    - Иметь несколько конфигураций (dev/prod/test)

    Returns:
        Настроенный экземпляр FastAPI
    """
    # ── Инициализация зависимостей ─────────────────────────────────────────
    question_provider = QuestionProvider()
    session_store = SessionStore(provider=question_provider)

    # ── Создание приложения ────────────────────────────────────────────────
    application = FastAPI(
        title="Выжить в Тайге — API",
        description=(
            "REST API для многопользовательского симулятора выживания. "
            "Принимает ответы игроков, управляет шкалами состояния и "
            "выдаёт вопросы по ОБЖ, ботанике и ориентированию."
        ),
        version="1.0.0",
        docs_url="/api/docs",       # Swagger UI
        redoc_url="/api/redoc",     # ReDoc
        openapi_url="/api/openapi.json",
    )

    # ── Подключение статических файлов ────────────────────────────────────
    # CSS, JS, изображения отдаются напрямую без FastAPI-обработки
    application.mount(
        "/static",
        StaticFiles(directory="web/static"),
        name="static",
    )

    # ── Подключение маршрутов с внедрёнными зависимостями ─────────────────
    router = create_router(session_store=session_store)
    application.include_router(router)

    # ── Обработчики событий жизненного цикла ──────────────────────────────

    @application.on_event("startup")
    async def on_startup() -> None:
        """
        Выполняется при запуске сервера.
        Предзагружаем вопросы, чтобы первый запрос не имел задержки.
        """
        logger.info("=" * 60)
        logger.info("🌲 Сервер 'Выжить в Тайге' запускается...")
        logger.info("=" * 60)

        try:
            questions = await question_provider.get_all_questions()
            logger.info("✅ Предзагружено %d вопросов из базы данных.", len(questions))
        except Exception as exc:
            logger.error("❌ Ошибка предзагрузки вопросов: %s", exc)

        logger.info("🌐 Документация API: http://127.0.0.1:8000/api/docs")
        logger.info("🎮 Интерфейс игры:   http://127.0.0.1:8000/")
        logger.info("=" * 60)

    @application.on_event("shutdown")
    async def on_shutdown() -> None:
        """Выполняется при остановке сервера."""
        logger.info("🛑 Сервер 'Выжить в Тайге' остановлен.")

    return application


# ─────────────────────────────────────────────────────────────────────────────
# Создание глобального экземпляра приложения
# (Uvicorn импортирует его по строке "main:app")
# ─────────────────────────────────────────────────────────────────────────────
app = create_app()


# ─────────────────────────────────────────────────────────────────────────────
# Точка входа для прямого запуска: python main.py
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("Запуск через python main.py")
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,            # Горячая перезагрузка при изменении файлов
        log_level="warning",    # Uvicorn не заглушает наш логгер
    )