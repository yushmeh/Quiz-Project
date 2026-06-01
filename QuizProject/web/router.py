# --- ФАЙЛ: web/router.py ---
"""
Веб-слой: FastAPI-маршруты (API endpoints).

Этот модуль — тонкая прослойка между HTTP и бизнес-логикой.
Единственные задачи:
  1. Десериализовать входящий HTTP-запрос в Python-типы
  2. Вызвать соответствующий метод бизнес-логики
  3. Сериализовать ответ обратно в JSON

Никакой бизнес-логики здесь быть не должно.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from core.quiz_engine import SessionStore
from core.score_manager import GameStatus
from utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Шаблонизатор — указываем директорию с HTML-файлами
# ---------------------------------------------------------------------------
templates = Jinja2Templates(directory="web/templates")

# ---------------------------------------------------------------------------
# Pydantic-модели запросов и ответов (контракт API)
# ---------------------------------------------------------------------------

class StartGameResponse(BaseModel):
    """Ответ на запрос начала новой игры."""
    session_id: str = Field(..., description="UUID игровой сессии")
    question_id: int = Field(..., description="ID первого вопроса")
    question_text: str = Field(..., description="Текст вопроса")
    question_category: str = Field(..., description="Категория вопроса")
    image_hint: str = Field(..., description="Эмодзи-иконка")
    answers: list[dict[str, Any]] = Field(..., description="Список вариантов (без is_correct!)")
    health: int = Field(..., description="Начальное здоровье")
    warmth: int = Field(..., description="Начальное тепло")
    satiety: int = Field(..., description="Начальная сытость")
    question_number: int = Field(..., description="Номер текущего вопроса")
    total_questions: int = Field(..., description="Всего вопросов")


class SubmitAnswerRequest(BaseModel):
    """Тело POST-запроса с ответом игрока."""
    session_id: str = Field(..., description="UUID сессии игрока")
    answer_id: str = Field(..., min_length=1, max_length=1, description="Буква ответа: a/b/c/d")


class SubmitAnswerResponse(BaseModel):
    """Ответ после обработки хода игрока."""
    is_correct: bool = Field(..., description="Правильный ли ответ")
    feedback: str = Field(..., description="Текстовое пояснение")
    health: int
    warmth: int
    satiety: int
    game_status: str = Field(..., description="alive | dead | rescued")
    # Следующий вопрос (None если игра закончена)
    next_question_id: int | None = None
    next_question_text: str | None = None
    next_question_category: str | None = None
    next_image_hint: str | None = None
    next_answers: list[dict[str, Any]] | None = None
    question_number: int = 0
    total_questions: int = 0


# ---------------------------------------------------------------------------
# Создание роутера
# ---------------------------------------------------------------------------

def create_router(session_store: SessionStore) -> APIRouter:
    """
    Фабричная функция: создаёт роутер с внедрённым SessionStore.

    Использование фабрики вместо глобальных переменных позволяет
    тестировать роутер с mock-зависимостями.

    Args:
        session_store: Хранилище игровых сессий

    Returns:
        Настроенный APIRouter
    """
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET / — главная страница (подача HTML)
    # ------------------------------------------------------------------

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        """
        Отдаёт единственную HTML-страницу приложения.
        Весь дальнейший UI управляется клиентским JavaScript через API.
        """
        return templates.TemplateResponse(request, name="index.html", context={})

    # ------------------------------------------------------------------
    # POST /api/game/start — начало новой игры
    # ------------------------------------------------------------------

    @router.post(
        "/api/game/start",
        response_model=StartGameResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Начать новую игровую сессию",
    )
    async def start_game() -> StartGameResponse:
        """
        Создаёт новую игровую сессию и возвращает первый вопрос.

        Клиент должен сохранить session_id для последующих запросов.
        """
        session_id, engine = await session_store.create_session()
        first_question = engine.get_current_question()

        if first_question is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось загрузить вопросы.",
            )

        score = engine.current_score
        logger.info("Начата новая игра: сессия %s", session_id)

        # Отдаём варианты ответов БЕЗ поля is_correct — это важно для честности!
        safe_answers = [
            {"id": ans.id, "text": ans.text}
            for ans in first_question.answers
        ]

        return StartGameResponse(
            session_id=session_id,
            question_id=first_question.id,
            question_text=first_question.text,
            question_category=first_question.category,
            image_hint=first_question.image_hint,
            answers=safe_answers,
            health=score.health,
            warmth=score.warmth,
            satiety=score.satiety,
            question_number=1,
            total_questions=engine.total_questions,
        )

    # ------------------------------------------------------------------
    # POST /api/game/answer — принять ответ игрока
    # ------------------------------------------------------------------

    @router.post(
        "/api/game/answer",
        response_model=SubmitAnswerResponse,
        summary="Отправить ответ на текущий вопрос",
    )
    async def submit_answer(body: SubmitAnswerRequest) -> SubmitAnswerResponse:
        """
        Обрабатывает выбранный ответ игрока:
        - Применяет эффекты на показатели
        - Определяет следующий вопрос или конец игры
        - Возвращает обновлённое состояние

        Body:
            session_id: UUID сессии
            answer_id:  Буква выбранного ответа

        Raises:
            404: Сессия не найдена
            409: Игра уже завершена
            422: Некорректный идентификатор ответа
        """
        engine = session_store.get_session(body.session_id)

        if engine is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Сессия '{body.session_id}' не найдена. Начните новую игру.",
            )

        if engine.is_finished:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Эта игровая сессия уже завершена.",
            )

        try:
            result = engine.submit_answer(body.answer_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        # Формируем данные о следующем вопросе (если есть)
        next_q = result.next_question
        next_safe_answers: list[dict[str, Any]] | None = None

        if next_q is not None:
            next_safe_answers = [
                {"id": ans.id, "text": ans.text}
                for ans in next_q.answers
            ]

        # Если игра завершена — убираем сессию из памяти
        if engine.is_finished:
            session_store.remove_session(body.session_id)

        return SubmitAnswerResponse(
            is_correct=result.is_correct,
            feedback=result.feedback,
            health=result.score.health,
            warmth=result.score.warmth,
            satiety=result.score.satiety,
            game_status=result.score.status.name.lower(),
            next_question_id=next_q.id if next_q else None,
            next_question_text=next_q.text if next_q else None,
            next_question_category=next_q.category if next_q else None,
            next_image_hint=next_q.image_hint if next_q else None,
            next_answers=next_safe_answers,
            question_number=result.question_number,
            total_questions=result.total_questions,
        )

    return router