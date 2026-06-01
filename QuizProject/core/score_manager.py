# --- ФАЙЛ: core/score_manager.py ---
"""
Слой бизнес-логики: менеджер состояния выживания игрока.

ScoreManager — единственный источник правды о состоянии показателей игрока.
Инкапсулирует правила изменения шкал, граничные условия (0..100),
и логику определения статуса «Жив/Мёртв».

Не знает ничего о HTTP, JSON, шаблонах или вопросах — только о числах.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Final, TypeAlias

from utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Константы игровой механики
# ---------------------------------------------------------------------------

STAT_MIN: Final[int] = 0     # Минимальное значение любой шкалы
STAT_MAX: Final[int] = 100   # Максимальное значение любой шкалы
STAT_DEFAULT: Final[int] = 80  # Стартовое значение каждой шкалы

# TypeAlias для ясности сигнатур
StatValue: TypeAlias = int  # Значение показателя в диапазоне [0, 100]


# ---------------------------------------------------------------------------
# Перечисление статусов игры
# ---------------------------------------------------------------------------

class GameStatus(Enum):
    """Возможные итоговые статусы игровой сессии."""
    ALIVE = auto()      # Игра продолжается
    DEAD = auto()       # Проигрыш — хотя бы одна шкала упала до 0
    RESCUED = auto()    # Победа — все вопросы пройдены, игрок спасён


# ---------------------------------------------------------------------------
# Объект-данные снимка состояния (для передачи в API-слой)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoreSnapshot:
    """
    Иммутабельный снимок текущего состояния всех трёх шкал.
    Используется для передачи данных между слоями без лишних зависимостей.
    """
    health: StatValue   # Здоровье [0..100]
    warmth: StatValue   # Тепло [0..100]
    satiety: StatValue  # Сытость [0..100]
    status: GameStatus  # Текущий статус игры

    @property
    def is_game_over(self) -> bool:
        """Удобное свойство: завершена ли игра (победа или поражение)."""
        return self.status in (GameStatus.DEAD, GameStatus.RESCUED)


# ---------------------------------------------------------------------------
# Основной класс менеджера состояния
# ---------------------------------------------------------------------------

class ScoreManager:
    """
    Управляет тремя показателями выживания: Здоровье, Тепло, Сытость.

    Обеспечивает:
    - Применение изменений показателей с зажимом в диапазон [0, 100]
    - Определение статуса игрока (живой/мёртвый/спасён)
    - Логирование критических событий
    - Создание иммутабельных снимков состояния

    Состояние хранится только в памяти в рамках одной сессии.
    Для персистентности требуется внешнее хранилище (не в рамках данного модуля).
    """

    def __init__(self) -> None:
        """Инициализирует все шкалы начальными значениями."""
        self._health: StatValue = STAT_DEFAULT
        self._warmth: StatValue = STAT_DEFAULT
        self._satiety: StatValue = STAT_DEFAULT
        self._status: GameStatus = GameStatus.ALIVE

        logger.info(
            "ScoreManager инициализирован: health=%d, warmth=%d, satiety=%d",
            self._health, self._warmth, self._satiety
        )

    # ------------------------------------------------------------------
    # Публичные свойства (только чтение)
    # ------------------------------------------------------------------

    @property
    def health(self) -> StatValue:
        """Текущее значение здоровья."""
        return self._health

    @property
    def warmth(self) -> StatValue:
        """Текущее значение тепла."""
        return self._warmth

    @property
    def satiety(self) -> StatValue:
        """Текущее значение сытости."""
        return self._satiety

    @property
    def status(self) -> GameStatus:
        """Текущий статус игровой сессии."""
        return self._status

    @property
    def is_alive(self) -> bool:
        """True, если игра ещё продолжается."""
        return self._status == GameStatus.ALIVE

    # ------------------------------------------------------------------
    # Основной метод изменения показателей
    # ------------------------------------------------------------------

    def apply_effects(
        self,
        *,
        health_delta: int = 0,
        warmth_delta: int = 0,
        satiety_delta: int = 0,
    ) -> ScoreSnapshot:
        """
        Применяет изменения ко всем трём шкалам и обновляет статус.

        Значения зажимаются в диапазон [STAT_MIN, STAT_MAX].
        Если хотя бы одна шкала достигает 0, статус меняется на DEAD.

        Args:
            health_delta:  Изменение здоровья (положительное или отрицательное)
            warmth_delta:  Изменение тепла
            satiety_delta: Изменение сытости

        Returns:
            Иммутабельный снимок нового состояния (ScoreSnapshot)
        """
        if not self.is_alive:
            logger.warning("Попытка изменить показатели завершённой игры. Игнорируется.")
            return self.snapshot()

        old_health, old_warmth, old_satiety = self._health, self._warmth, self._satiety

        # Применяем дельты с зажимом в допустимый диапазон
        self._health = self._clamp(self._health + health_delta)
        self._warmth = self._clamp(self._warmth + warmth_delta)
        self._satiety = self._clamp(self._satiety + satiety_delta)

        logger.debug(
            "Показатели изменены: health %d→%d (Δ%+d), warmth %d→%d (Δ%+d), satiety %d→%d (Δ%+d)",
            old_health, self._health, health_delta,
            old_warmth, self._warmth, warmth_delta,
            old_satiety, self._satiety, satiety_delta,
        )

        # Проверяем критическое падение шкал
        self._check_critical_stats()

        # Обновляем статус жизни/смерти
        self._update_status()

        return self.snapshot()

    def mark_rescued(self) -> ScoreSnapshot:
        """
        Устанавливает статус «Спасён» при успешном прохождении всех вопросов.

        Returns:
            Снимок финального состояния
        """
        if self.is_alive:
            self._status = GameStatus.RESCUED
            logger.info(
                "Игрок СПАСЁН! Финальные показатели: health=%d, warmth=%d, satiety=%d",
                self._health, self._warmth, self._satiety
            )
        return self.snapshot()

    def snapshot(self) -> ScoreSnapshot:
        """
        Создаёт иммутабельный снимок текущего состояния.

        Returns:
            Объект ScoreSnapshot с текущими значениями всех полей
        """
        return ScoreSnapshot(
            health=self._health,
            warmth=self._warmth,
            satiety=self._satiety,
            status=self._status,
        )

    # ------------------------------------------------------------------
    # Приватные вспомогательные методы
    # ------------------------------------------------------------------

    @staticmethod
    def _clamp(value: int) -> StatValue:
        """
        Ограничивает значение диапазоном [STAT_MIN, STAT_MAX].

        Args:
            value: Произвольное целое число

        Returns:
            Значение, зажатое в допустимый диапазон
        """
        return max(STAT_MIN, min(STAT_MAX, value))

    def _check_critical_stats(self) -> None:
        """
        Логирует предупреждения при критически низких значениях показателей.
        Порог критичности — 25% от максимума.
        """
        critical_threshold = STAT_MAX // 4  # 25

        if self._health <= critical_threshold and self._health > STAT_MIN:
            logger.warning("КРИТИЧНО: Здоровье упало до %d!", self._health)
        if self._warmth <= critical_threshold and self._warmth > STAT_MIN:
            logger.warning("КРИТИЧНО: Тепло упало до %d!", self._warmth)
        if self._satiety <= critical_threshold and self._satiety > STAT_MIN:
            logger.warning("КРИТИЧНО: Сытость упала до %d!", self._satiety)

    def _update_status(self) -> None:
        """
        Проверяет условие поражения: хотя бы одна шкала достигла нуля.
        Обновляет статус и логирует событие гибели.
        """
        dead_stats: list[str] = []

        if self._health <= STAT_MIN:
            dead_stats.append("Здоровье")
        if self._warmth <= STAT_MIN:
            dead_stats.append("Тепло")
        if self._satiety <= STAT_MIN:
            dead_stats.append("Сытость")

        if dead_stats:
            self._status = GameStatus.DEAD
            logger.warning(
                "ИГРОК ПОГИБ! Обнулённые шкалы: %s. "
                "Финальные значения: health=%d, warmth=%d, satiety=%d",
                ", ".join(dead_stats), self._health, self._warmth, self._satiety
            )