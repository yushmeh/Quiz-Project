# --- ФАЙЛ: core/quiz_engine.py ---
"""
Слой бизнес-логики: движок игровых сессий.

QuizEngine — оркестратор, связывающий данные (QuestionProvider)
с состоянием (ScoreManager). Управляет жизненным циклом одной игровой сессии:
создание → получение вопроса → принятие ответа → завершение.

Каждая HTTP-сессия получает свой экземпляр QuizEngine через SessionStore.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TypeAlias

from data.question_provider import Answer, Question, QuestionId, QuestionProvider
from core.score_manager import GameStatus, ScoreManager, ScoreSnapshot
from utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Типы идентификаторов
# ---------------------------------------------------------------------------
SessionId: TypeAlias = str  # UUID игровой сессии


# ---------------------------------------------------------------------------
# Объекты передачи данных между движком и API-слоем
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnswerResult:
    """
    Результат обработки ответа игрока.
    Содержит всё необходимое для обновления UI на клиенте.
    """
    is_correct: bool            # Правильный ли ответ
    feedback: str               # Текстовое объяснение для игрока
    score: ScoreSnapshot        # Новое состояние шкал
    next_question: Question | None  # Следующий вопрос или None (игра завершена)
    question_number: int        # Номер текущего вопроса (для прогресс-бара)
    total_questions: int        # Общее количество вопросов в сессии


@dataclass(frozen=True)
class SessionState:
    """
    Полное состояние сессии для передачи клиенту при инициализации.
    """
    session_id: SessionId       # Уникальный ID этой сессии
    current_question: Question  # Первый вопрос для отображения
    score: ScoreSnapshot        # Начальное состояние шкал
    total_questions: int        # Общее число вопросов


# ---------------------------------------------------------------------------
# Основной класс игрового движка
# ---------------------------------------------------------------------------

class QuizEngine:
    """
    Управляет жизненным циклом одной игровой сессии.

    Принцип работы:
    1. При создании загружает перемешанный список вопросов
    2. Отдаёт вопросы по одному через next_question()
    3. Принимает ответ через submit_answer(), делегируя эффекты в ScoreManager
    4. Определяет конец игры (победа/поражение)

    Каждая сессия независима и имеет собственный ScoreManager.
    """

    def __init__(
        self,
        questions: list[Question],
        session_id: SessionId,
    ) -> None:
        """
        Инициализирует сессию с уже загруженными вопросами.

        Args:
            questions: Перемешанный список вопросов для данной сессии
            session_id: Уникальный идентификатор сессии
        """
        self._session_id: SessionId = session_id
        self._questions: list[Question] = questions
        self._current_index: int = 0
        self._score_manager: ScoreManager = ScoreManager()
        self._is_finished: bool = False

        logger.info(
            "Игровая сессия создана: id=%s, вопросов=%d",
            session_id, len(questions)
        )

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> SessionId:
        """Идентификатор данной сессии."""
        return self._session_id

    @property
    def is_finished(self) -> bool:
        """True, если игра завершена (победа или поражение)."""
        return self._is_finished

    @property
    def total_questions(self) -> int:
        """Общее количество вопросов в этой сессии."""
        return len(self._questions)

    @property
    def current_question_number(self) -> int:
        """Номер текущего вопроса (1-based), для отображения прогресса."""
        return min(self._current_index + 1, self.total_questions)

    @property
    def current_score(self) -> ScoreSnapshot:
        """Текущий снимок состояния шкал."""
        return self._score_manager.snapshot()

    # ------------------------------------------------------------------
    # Получение текущего вопроса
    # ------------------------------------------------------------------

    def get_current_question(self) -> Question | None:
        """
        Возвращает текущий вопрос без продвижения указателя.

        Returns:
            Question или None, если вопросы закончились
        """
        if self._current_index < len(self._questions):
            return self._questions[self._current_index]
        return None

    # ------------------------------------------------------------------
    # Обработка ответа — центральная бизнес-логика
    # ------------------------------------------------------------------

    def submit_answer(self, answer_id: str) -> AnswerResult:
        """
        Принимает ответ игрока, применяет эффекты и возвращает результат.

        Алгоритм:
        1. Находим текущий вопрос
        2. Ищем выбранный вариант ответа
        3. Применяем эффекты через ScoreManager
        4. Проверяем условие завершения игры
        5. Возвращаем AnswerResult с новым состоянием

        Args:
            answer_id: Буква выбранного ответа ("a", "b", "c", "d")

        Returns:
            Объект AnswerResult с результатами хода

        Raises:
            ValueError: Если игра уже завершена или вопрос/ответ не найден
        """
        if self._is_finished:
            raise ValueError("Нельзя отвечать на вопросы завершённой сессии.")

        current_question = self.get_current_question()
        if current_question is None:
            raise ValueError("Нет активного вопроса для ответа.")

        # Находим выбранный вариант ответа
        chosen_answer: Answer | None = current_question.get_answer_by_id(answer_id)
        if chosen_answer is None:
            raise ValueError(f"Неверный идентификатор ответа: '{answer_id}'")

        logger.info(
            "Сессия %s | Вопрос %d/%d | Ответ: '%s' (верный: %s)",
            self._session_id,
            self.current_question_number,
            self.total_questions,
            answer_id,
            chosen_answer.is_correct,
        )

        # Делегируем применение эффектов в ScoreManager
        effects = chosen_answer.effects
        new_score: ScoreSnapshot = self._score_manager.apply_effects(
            health_delta=effects.health,
            warmth_delta=effects.warmth,
            satiety_delta=effects.satiety,
        )

        # Продвигаем указатель к следующему вопросу
        self._current_index += 1

        # Определяем следующий вопрос или завершаем игру
        next_question: Question | None = None

        if new_score.status == GameStatus.DEAD:
            # Поражение — шкала упала до нуля
            self._is_finished = True
            logger.info("Сессия %s завершена: ПОРАЖЕНИЕ", self._session_id)

        elif self._current_index >= len(self._questions):
            # Все вопросы пройдены — победа!
            final_score = self._score_manager.mark_rescued()
            self._is_finished = True
            logger.info("Сессия %s завершена: ПОБЕДА", self._session_id)
            # Используем финальный снимок с RESCUED статусом
            return AnswerResult(
                is_correct=chosen_answer.is_correct,
                feedback=chosen_answer.feedback,
                score=final_score,
                next_question=None,
                question_number=self.total_questions,
                total_questions=self.total_questions,
            )
        else:
            # Игра продолжается — берём следующий вопрос
            next_question = self.get_current_question()

        return AnswerResult(
            is_correct=chosen_answer.is_correct,
            feedback=chosen_answer.feedback,
            score=new_score,
            next_question=next_question,
            question_number=self._current_index,  # Уже проинкрементирован
            total_questions=self.total_questions,
        )


# ---------------------------------------------------------------------------
# Хранилище сессий (в памяти, без персистентности)
# ---------------------------------------------------------------------------

class SessionStore:
    """
    Хранит активные игровые сессии в памяти процесса.

    В production-среде заменить на Redis или другое внешнее хранилище.
    Здесь — простой dict для учебного проекта.

    Фабричный метод create_session() скрывает создание QuizEngine
    от API-слоя, соблюдая принцип инверсии зависимостей.
    """

    def __init__(self, provider: QuestionProvider) -> None:
        """
        Args:
            provider: Провайдер вопросов (внедрение зависимости)
        """
        self._provider: QuestionProvider = provider
        self._sessions: dict[SessionId, QuizEngine] = {}

    async def create_session(self) -> tuple[SessionId, QuizEngine]:
        """
        Создаёт новую игровую сессию с уникальным UUID.

        Загружает перемешанные вопросы из провайдера,
        создаёт новый QuizEngine и сохраняет его в хранилище.

        Returns:
            Кортеж (session_id, engine) для дальнейшей работы
        """
        session_id: SessionId = str(uuid.uuid4())
        questions = await self._provider.get_shuffled_questions()
        engine = QuizEngine(questions=questions, session_id=session_id)
        self._sessions[session_id] = engine

        logger.info("Новая сессия зарегистрирована: %s", session_id)
        return session_id, engine

    def get_session(self, session_id: SessionId) -> QuizEngine | None:
        """
        Возвращает активный движок по ID сессии.

        Args:
            session_id: UUID сессии из cookie или заголовка клиента

        Returns:
            QuizEngine или None, если сессия не найдена / истекла
        """
        return self._sessions.get(session_id)

    def remove_session(self, session_id: SessionId) -> None:
        """
        Удаляет завершённую сессию из хранилища (освобождение памяти).

        Args:
            session_id: UUID сессии для удаления
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info("Сессия удалена из хранилища: %s", session_id)