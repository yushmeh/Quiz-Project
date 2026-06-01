# --- ФАЙЛ: tests/test_quiz.py ---
"""
Набор unit-тестов для бизнес-логики симулятора "Выжить в Тайге".

Покрывает:
- ScoreManager: изменение шкал, зажим значений, определение статусов
- QuizEngine: обработка ответов, переход между вопросами, конец игры
- Интеграция: полный цикл победы и поражения

Запуск:
    pytest tests/test_quiz.py -v
    pytest tests/test_quiz.py -v --tb=short    # Краткие трейсбеки
"""

from __future__ import annotations

import pytest

from core.score_manager import (
    STAT_DEFAULT, STAT_MAX, STAT_MIN,
    GameStatus, ScoreManager, ScoreSnapshot,
)
from core.quiz_engine import QuizEngine, SessionStore
from data.question_provider import Answer, AnswerEffects, Question, QuestionProvider


# ─────────────────────────────────────────────────────────────────────────────
# Фикстуры — создание тестовых объектов
# ─────────────────────────────────────────────────────────────────────────────

def make_answer(
    answer_id: str = "a",
    is_correct: bool = True,
    health: int = 0,
    warmth: int = 0,
    satiety: int = 0,
    feedback: str = "Тестовый фидбэк",
) -> Answer:
    """Фабрика тестового варианта ответа."""
    return Answer(
        id=answer_id,
        text=f"Вариант {answer_id}",
        is_correct=is_correct,
        effects=AnswerEffects(health=health, warmth=warmth, satiety=satiety),
        feedback=feedback,
    )


def make_question(
    question_id: int = 1,
    answers: list[Answer] | None = None,
) -> Question:
    """Фабрика тестового вопроса."""
    if answers is None:
        answers = [
            make_answer("a", is_correct=True,  health=10, warmth=5,   satiety=0),
            make_answer("b", is_correct=False, health=-20, warmth=-10, satiety=-5),
        ]
    return Question(
        id=question_id,
        category="Тест",
        text=f"Тестовый вопрос #{question_id}",
        image_hint="🧪",
        answers=answers,
    )


def make_engine(num_questions: int = 3, session_id: str = "test-session") -> QuizEngine:
    """Фабрика игрового движка с N тестовыми вопросами."""
    questions = [make_question(i + 1) for i in range(num_questions)]
    return QuizEngine(questions=questions, session_id=session_id)


# ─────────────────────────────────────────────────────────────────────────────
# Тесты ScoreManager
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreManagerInit:
    """Тесты инициализации ScoreManager."""

    def test_initial_values_are_default(self):
        """Все шкалы должны быть равны STAT_DEFAULT при создании."""
        sm = ScoreManager()
        assert sm.health == STAT_DEFAULT
        assert sm.warmth == STAT_DEFAULT
        assert sm.satiety == STAT_DEFAULT

    def test_initial_status_is_alive(self):
        """Начальный статус — ALIVE."""
        sm = ScoreManager()
        assert sm.status == GameStatus.ALIVE
        assert sm.is_alive is True

    def test_snapshot_reflects_initial_state(self):
        """Снимок должен соответствовать начальному состоянию."""
        sm = ScoreManager()
        snap = sm.snapshot()
        assert isinstance(snap, ScoreSnapshot)
        assert snap.health == STAT_DEFAULT
        assert snap.warmth == STAT_DEFAULT
        assert snap.satiety == STAT_DEFAULT
        assert snap.status == GameStatus.ALIVE


class TestScoreManagerApplyEffects:
    """Тесты метода apply_effects."""

    def test_positive_effects_increase_stats(self):
        """Положительные дельты увеличивают показатели."""
        sm = ScoreManager()
        sm._health = 50  # Устанавливаем напрямую для теста
        snap = sm.apply_effects(health_delta=10)
        assert snap.health == 60

    def test_negative_effects_decrease_stats(self):
        """Отрицательные дельты уменьшают показатели."""
        sm = ScoreManager()
        snap = sm.apply_effects(warmth_delta=-15)
        assert snap.warmth == STAT_DEFAULT - 15

    def test_stat_clamp_at_maximum(self):
        """Значение не должно превышать STAT_MAX."""
        sm = ScoreManager()
        snap = sm.apply_effects(health_delta=100)  # 80 + 100 = 180, но должно быть 100
        assert snap.health == STAT_MAX

    def test_stat_clamp_at_minimum(self):
        """Значение не должно опускаться ниже STAT_MIN."""
        sm = ScoreManager()
        snap = sm.apply_effects(satiety_delta=-200)  # Огромный штраф
        assert snap.satiety == STAT_MIN

    def test_all_stats_change_simultaneously(self):
        """Все три шкалы меняются в одном вызове."""
        sm = ScoreManager()
        snap = sm.apply_effects(health_delta=-10, warmth_delta=5, satiety_delta=-20)
        assert snap.health == STAT_DEFAULT - 10
        assert snap.warmth == STAT_DEFAULT + 5
        assert snap.satiety == STAT_DEFAULT - 20

    def test_zero_delta_does_not_change_stat(self):
        """Нулевая дельта не изменяет значение."""
        sm = ScoreManager()
        original = sm.snapshot()
        snap = sm.apply_effects()
        assert snap.health == original.health
        assert snap.warmth == original.warmth
        assert snap.satiety == original.satiety


class TestScoreManagerDeathCondition:
    """Тесты условий поражения."""

    def test_health_zero_causes_death(self):
        """Обнуление здоровья → статус DEAD."""
        sm = ScoreManager()
        snap = sm.apply_effects(health_delta=-100)
        assert snap.health == STAT_MIN
        assert snap.status == GameStatus.DEAD
        assert sm.is_alive is False

    def test_warmth_zero_causes_death(self):
        """Обнуление тепла → статус DEAD."""
        sm = ScoreManager()
        snap = sm.apply_effects(warmth_delta=-100)
        assert snap.status == GameStatus.DEAD

    def test_satiety_zero_causes_death(self):
        """Обнуление сытости → статус DEAD."""
        sm = ScoreManager()
        snap = sm.apply_effects(satiety_delta=-100)
        assert snap.status == GameStatus.DEAD

    def test_status_alive_when_all_stats_above_zero(self):
        """Статус ALIVE пока все шкалы > 0."""
        sm = ScoreManager()
        snap = sm.apply_effects(health_delta=-79, warmth_delta=-79, satiety_delta=-79)
        # 80 - 79 = 1 для каждой шкалы
        assert snap.health == 1
        assert snap.warmth == 1
        assert snap.satiety == 1
        assert snap.status == GameStatus.ALIVE

    def test_effects_ignored_after_death(self):
        """После смерти дальнейшие эффекты игнорируются."""
        sm = ScoreManager()
        sm.apply_effects(health_delta=-100)  # Убиваем игрока
        snap = sm.apply_effects(health_delta=50)  # Пытаемся восстановить
        assert snap.status == GameStatus.DEAD
        assert snap.health == STAT_MIN  # Значение не изменилось


class TestScoreManagerRescue:
    """Тесты статуса RESCUED."""

    def test_mark_rescued_sets_status(self):
        """mark_rescued() устанавливает статус RESCUED."""
        sm = ScoreManager()
        snap = sm.mark_rescued()
        assert snap.status == GameStatus.RESCUED

    def test_rescued_is_game_over(self):
        """RESCUED считается завершением игры."""
        sm = ScoreManager()
        sm.mark_rescued()
        snap = sm.snapshot()
        assert snap.is_game_over is True

    def test_dead_is_game_over(self):
        """DEAD считается завершением игры."""
        sm = ScoreManager()
        sm.apply_effects(health_delta=-100)
        snap = sm.snapshot()
        assert snap.is_game_over is True

    def test_alive_is_not_game_over(self):
        """ALIVE не является завершением игры."""
        sm = ScoreManager()
        snap = sm.snapshot()
        assert snap.is_game_over is False


# ─────────────────────────────────────────────────────────────────────────────
# Тесты QuizEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestQuizEngineInit:
    """Тесты инициализации игрового движка."""

    def test_initial_state(self):
        """Движок создаётся с корректными начальными значениями."""
        engine = make_engine(num_questions=5)
        assert engine.total_questions == 5
        assert engine.is_finished is False
        assert engine.current_question_number == 1

    def test_first_question_is_available(self):
        """Первый вопрос доступен сразу после создания."""
        engine = make_engine()
        q = engine.get_current_question()
        assert q is not None
        assert isinstance(q, Question)

    def test_empty_engine_has_no_question(self):
        """Движок без вопросов не имеет текущего вопроса."""
        engine = QuizEngine(questions=[], session_id="empty")
        assert engine.get_current_question() is None


class TestQuizEngineSubmitAnswer:
    """Тесты обработки ответов."""

    def test_correct_answer_applies_positive_effects(self):
        """Правильный ответ применяет положительные эффекты."""
        engine = make_engine(num_questions=3)
        initial_health = engine.current_score.health

        result = engine.submit_answer("a")  # "a" — правильный с +10 здоровья

        assert result.is_correct is True
        assert result.score.health == initial_health + 10

    def test_wrong_answer_applies_negative_effects(self):
        """Неправильный ответ применяет штрафы."""
        engine = make_engine(num_questions=3)
        initial_health = engine.current_score.health

        result = engine.submit_answer("b")  # "b" — неправильный с -20 здоровья

        assert result.is_correct is False
        assert result.score.health == initial_health - 20

    def test_answer_advances_question_pointer(self):
        """После ответа указатель смещается к следующему вопросу."""
        engine = make_engine(num_questions=3)
        first_question = engine.get_current_question()
        engine.submit_answer("a")
        second_question = engine.get_current_question()

        assert first_question is not None
        assert second_question is not None
        assert first_question.id != second_question.id

    def test_invalid_answer_id_raises_error(self):
        """Несуществующий ID ответа вызывает ValueError."""
        engine = make_engine()
        with pytest.raises(ValueError, match="Неверный идентификатор ответа"):
            engine.submit_answer("z")

    def test_answer_on_finished_engine_raises_error(self):
        """Ответ в завершённой сессии вызывает ValueError."""
        engine = make_engine(num_questions=1)
        engine.submit_answer("a")  # Заканчиваем игру
        with pytest.raises(ValueError, match="завершённой"):
            engine.submit_answer("a")


class TestQuizEngineGameFlow:
    """Тесты полного цикла игры."""

    def test_finishing_all_questions_sets_rescued(self):
        """Прохождение всех вопросов завершает игру победой."""
        engine = make_engine(num_questions=2)

        result1 = engine.submit_answer("a")
        assert result1.score.status == GameStatus.ALIVE
        assert engine.is_finished is False

        result2 = engine.submit_answer("a")  # Последний вопрос
        assert result2.score.status == GameStatus.RESCUED
        assert engine.is_finished is True

    def test_winning_result_has_no_next_question(self):
        """При победе в результате нет следующего вопроса."""
        engine = make_engine(num_questions=1)
        result = engine.submit_answer("a")
        assert result.next_question is None

    def test_death_ends_game(self):
        """Ответ, обнуляющий шкалу, завершает игру поражением."""
        # Создаём вопрос, где неверный ответ убивает игрока
        lethal_answer = make_answer("b", is_correct=False, health=-100)
        question = make_question(answers=[
            make_answer("a", is_correct=True),
            lethal_answer,
        ])
        engine = QuizEngine(questions=[question, question], session_id="death-test")

        result = engine.submit_answer("b")  # Летальный ответ

        assert result.score.status == GameStatus.DEAD
        assert engine.is_finished is True

    def test_next_question_provided_mid_game(self):
        """В середине игры результат содержит следующий вопрос."""
        engine = make_engine(num_questions=3)
        result = engine.submit_answer("a")
        assert result.next_question is not None
        assert isinstance(result.next_question, Question)

    def test_question_numbers_progress_correctly(self):
        """Номера вопросов корректно инкрементируются."""
        engine = make_engine(num_questions=3)
        assert engine.total_questions == 3

        result1 = engine.submit_answer("a")
        assert result1.question_number == 1
        assert result1.total_questions == 3

        result2 = engine.submit_answer("a")
        assert result2.question_number == 2


class TestQuestionGetAnswerById:
    """Тесты метода Question.get_answer_by_id."""

    def test_finds_existing_answer(self):
        """Возвращает корректный ответ по ID."""
        question = make_question()
        answer = question.get_answer_by_id("a")
        assert answer is not None
        assert answer.id == "a"

    def test_returns_none_for_missing_answer(self):
        """Возвращает None для несуществующего ID."""
        question = make_question()
        answer = question.get_answer_by_id("z")
        assert answer is None


# ─────────────────────────────────────────────────────────────────────────────
# Интеграционные тесты (асинхронные)
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionStore:
    """Тесты хранилища сессий."""

    @pytest.mark.asyncio
    async def test_create_and_get_session(self):
        """Созданная сессия доступна по ID."""
        provider = QuestionProvider()
        store = SessionStore(provider=provider)
        session_id, engine = await store.create_session()

        retrieved = store.get_session(session_id)
        assert retrieved is engine

    @pytest.mark.asyncio
    async def test_get_nonexistent_session_returns_none(self):
        """Несуществующий ID возвращает None."""
        provider = QuestionProvider()
        store = SessionStore(provider=provider)

        result = store.get_session("no-such-session")
        assert result is None

    @pytest.mark.asyncio
    async def test_remove_session(self):
        """Удалённая сессия больше не доступна."""
        provider = QuestionProvider()
        store = SessionStore(provider=provider)
        session_id, _ = await store.create_session()

        store.remove_session(session_id)
        assert store.get_session(session_id) is None

    @pytest.mark.asyncio
    async def test_different_sessions_are_independent(self):
        """Разные сессии имеют независимое состояние."""
        provider = QuestionProvider()
        store = SessionStore(provider=provider)

        id1, engine1 = await store.create_session()
        id2, engine2 = await store.create_session()

        assert id1 != id2
        assert engine1 is not engine2