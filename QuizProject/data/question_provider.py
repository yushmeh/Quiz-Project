# --- ФАЙЛ: data/question_provider.py ---
"""
Слой данных: асинхронный провайдер вопросов.

Отвечает исключительно за загрузку и десериализацию данных из JSON-файла
в строго типизированные объекты-данные (dataclasses).
Не содержит никакой бизнес-логики.

Соответствует принципу Single Responsibility (SRP) архитектуры Clean Architecture.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias

import aiofiles  # pip install aiofiles

from utils.logger import get_logger

# ---------------------------------------------------------------------------
# Настройка логгера для данного модуля
# ---------------------------------------------------------------------------
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# TypeAlias — современный способ объявить псевдоним типа (PEP 613 / Python 3.10+)
# ---------------------------------------------------------------------------
AnswerId: TypeAlias = str          # "a", "b", "c", "d"
StatDelta: TypeAlias = int         # Целочисленное изменение показателя (-30..+20)
QuestionId: TypeAlias = int        # Уникальный идентификатор вопроса


# ---------------------------------------------------------------------------
# Доменные объекты-данные (Data Transfer Objects)
# Используем @dataclass для автоматической генерации __init__, __repr__ и т.д.
# frozen=True делает объекты неизменяемыми — иммутабельность данных.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AnswerEffects:
    """
    Описывает влияние выбранного ответа на три показателя выживания игрока.
    Значения могут быть как положительными (бонус), так и отрицательными (штраф).
    """
    health: StatDelta   # Изменение здоровья
    warmth: StatDelta   # Изменение тепла
    satiety: StatDelta  # Изменение сытости


@dataclass(frozen=True)
class Answer:
    """
    Один вариант ответа на вопрос.
    Содержит текст, корректность, эффекты на показатели и обратную связь для игрока.
    """
    id: AnswerId            # Буква варианта: "a", "b", "c", "d"
    text: str               # Текст варианта для отображения
    is_correct: bool        # Является ли ответ правильным
    effects: AnswerEffects  # Влияние на показатели
    feedback: str           # Сообщение игроку после выбора этого ответа


@dataclass(frozen=True)
class Question:
    """
    Полное описание одного вопроса викторины.
    Является основным доменным объектом слоя данных.
    """
    id: QuestionId          # Уникальный числовой ID
    category: str           # Тематическая категория (ОБЖ, ботаника и т.д.)
    text: str               # Текст вопроса
    image_hint: str         # Эмодзи-подсказка для UI
    answers: list[Answer]   # Список вариантов ответов (обычно 4)

    def get_answer_by_id(self, answer_id: AnswerId) -> Answer | None:
        """
        Находит вариант ответа по его буквенному идентификатору.

        Args:
            answer_id: Буква варианта ("a", "b", "c", "d")

        Returns:
            Объект Answer или None, если не найден
        """
        for answer in self.answers:
            if answer.id == answer_id:
                return answer
        return None


# ---------------------------------------------------------------------------
# Провайдер данных — единственный класс, работающий с файловой системой
# ---------------------------------------------------------------------------

class QuestionProvider:
    """
    Асинхронный загрузчик и хранилище вопросов из JSON-файла.

    Использует ленивую инициализацию: данные загружаются один раз
    при первом обращении и кешируются в памяти.

    Пример использования:
        provider = QuestionProvider()
        questions = await provider.get_all_questions()
        shuffled = await provider.get_shuffled_questions()
    """

    # Путь к файлу данных относительно корня проекта
    _DATA_FILE: Path = Path(__file__).parent / "questions.json"

    def __init__(self) -> None:
        # Кеш загруженных вопросов. None означает "не загружено".
        self._questions_cache: list[Question] | None = None

    async def _load_from_file(self) -> list[Question]:
        """
        Читает JSON-файл асинхронно и десериализует данные в объекты Question.

        Использует aiofiles для неблокирующего чтения, чтобы не блокировать
        event loop FastAPI во время дисковых операций.

        Returns:
            Список объектов Question

        Raises:
            FileNotFoundError: Если файл questions.json не найден
            ValueError: Если JSON имеет неверную структуру
        """
        logger.info("Загрузка вопросов из файла: %s", self._DATA_FILE)

        if not self._DATA_FILE.exists():
            logger.error("Файл данных не найден: %s", self._DATA_FILE)
            raise FileNotFoundError(f"Файл вопросов не найден: {self._DATA_FILE}")

        async with aiofiles.open(self._DATA_FILE, encoding="utf-8") as f:
            raw_content = await f.read()

        try:
            raw_data: list[dict] = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            logger.error("Ошибка парсинга JSON: %s", exc)
            raise ValueError(f"Некорректный JSON в файле вопросов: {exc}") from exc

        questions = [self._deserialize_question(item) for item in raw_data]
        logger.info("Успешно загружено %d вопросов", len(questions))
        return questions

    @staticmethod
    def _deserialize_question(data: dict) -> Question:
        """
        Преобразует словарь из JSON в строго типизированный объект Question.

        Args:
            data: Словарь с данными вопроса из JSON

        Returns:
            Объект Question с вложенными объектами Answer и AnswerEffects
        """
        answers = [
            Answer(
                id=ans["id"],
                text=ans["text"],
                is_correct=ans["is_correct"],
                effects=AnswerEffects(
                    health=ans["effects"]["health"],
                    warmth=ans["effects"]["warmth"],
                    satiety=ans["effects"]["satiety"],
                ),
                feedback=ans["feedback"],
            )
            for ans in data["answers"]
        ]

        return Question(
            id=data["id"],
            category=data["category"],
            text=data["text"],
            image_hint=data["image_hint"],
            answers=answers,
        )

    async def get_all_questions(self) -> list[Question]:
        """
        Возвращает все вопросы. При первом вызове загружает из файла.

        Returns:
            Список всех объектов Question
        """
        if self._questions_cache is None:
            self._questions_cache = await self._load_from_file()
        return self._questions_cache

    async def get_shuffled_questions(self) -> list[Question]:
        """
        Возвращает вопросы в случайном порядке для реиграбельности.

        Returns:
            Перемешанный список объектов Question
        """
        all_questions = await self.get_all_questions()
        shuffled = list(all_questions)  # Копируем, не мутируем оригинал
        random.shuffle(shuffled)
        return shuffled

    async def get_question_by_id(self, question_id: QuestionId) -> Question | None:
        """
        Находит вопрос по уникальному ID.

        Args:
            question_id: Числовой ID вопроса

        Returns:
            Объект Question или None, если не найден
        """
        all_questions = await self.get_all_questions()
        for question in all_questions:
            if question.id == question_id:
                return question
        return None