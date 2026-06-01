// --- ФАЙЛ: web/static/js/app.js ---
/**
 * Клиентская логика симулятора "Выжить в Тайге".
 *
 * Архитектура:
 * - Все взаимодействия с сервером — через fetch() (асинхронно, без перезагрузок)
 * - Состояние приложения хранится в объекте AppState
 * - UI обновляется только через чистые функции-рендеры
 * - Никаких глобальных переменных кроме объекта app
 */

"use strict";

// ─────────────────────────────────────────────────────────────────────────────
// Конфигурация
// ─────────────────────────────────────────────────────────────────────────────
const CONFIG = {
    API_BASE: "",                   // Пустая строка = тот же хост (FastAPI)
    ENDPOINTS: {
        START:  "/api/game/start",
        ANSWER: "/api/game/answer",
    },
    FEEDBACK_DELAY_MS: 800,         // Задержка перед показом кнопки "Следующий"
    TOAST_DURATION_MS: 4000,        // Длительность показа ошибок
    CRITICAL_THRESHOLD: 25,         // Порог критического состояния шкалы (%)
};

// ─────────────────────────────────────────────────────────────────────────────
// Состояние приложения
// ─────────────────────────────────────────────────────────────────────────────
const AppState = {
    sessionId: null,                // UUID текущей сессии
    currentAnswer: null,            // Данные последнего ответа (для перехода)
    isWaitingForNext: false,        // Ждём ли нажатия "Следующий вопрос"
    isLoading: false,               // Идёт ли запрос к серверу
};

// ─────────────────────────────────────────────────────────────────────────────
// DOM-элементы (кешируем при первом обращении)
// ─────────────────────────────────────────────────────────────────────────────
const DOM = {
    get welcomeScreen()    { return document.getElementById("welcome-screen"); },
    get questionCard()     { return document.getElementById("question-card"); },
    get gameOverScreen()   { return document.getElementById("game-over-screen"); },
    get questionText()     { return document.getElementById("question-text"); },
    get questionHintIcon() { return document.getElementById("question-hint-icon"); },
    get answersGrid()      { return document.getElementById("answers-grid"); },
    get feedbackBox()      { return document.getElementById("feedback-box"); },
    get feedbackIcon()     { return document.getElementById("feedback-icon"); },
    get feedbackText()     { return document.getElementById("feedback-text"); },
    get btnNext()          { return document.getElementById("btn-next"); },
    get btnStart()         { return document.getElementById("btn-start"); },
    get toast()            { return document.getElementById("toast"); },
    // Шкалы выживания
    get healthBar()        { return document.getElementById("health-bar"); },
    get warmthBar()        { return document.getElementById("warmth-bar"); },
    get satietyBar()       { return document.getElementById("satiety-bar"); },
    get progressBar()      { return document.getElementById("progress-bar"); },
    get healthValue()      { return document.getElementById("health-value"); },
    get warmthValue()      { return document.getElementById("warmth-value"); },
    get satietyValue()     { return document.getElementById("satiety-value"); },
    get progressText()     { return document.getElementById("progress-text"); },
    // Категория
    get categoryBadge()    { return document.getElementById("category-badge"); },
    get categoryText()     { return document.getElementById("category-text"); },
    get categoryIcon()     { return document.getElementById("category-icon"); },
    // Финальный экран
    get gameOverIcon()     { return document.getElementById("game-over-icon"); },
    get gameOverTitle()    { return document.getElementById("game-over-title"); },
    get gameOverText()     { return document.getElementById("game-over-text"); },
    get finalStats()       { return document.getElementById("final-stats"); },
};

// ─────────────────────────────────────────────────────────────────────────────
// API-клиент
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Выполняет POST-запрос к серверу и возвращает распарсенный JSON.
 *
 * @param {string} endpoint - URL эндпоинта
 * @param {object} body     - Тело запроса (будет сериализовано в JSON)
 * @returns {Promise<object>} Ответ сервера
 * @throws {Error} При ошибке сети или ответе сервера с кодом >= 400
 */
async function apiPost(endpoint, body = {}) {
    const response = await fetch(CONFIG.API_BASE + endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });

    if (!response.ok) {
        let errorMessage = `Ошибка сервера: ${response.status}`;
        try {
            const errorData = await response.json();
            errorMessage = errorData.detail || errorMessage;
        } catch (_) {
            // Игнорируем ошибки парсинга JSON ошибки
        }
        throw new Error(errorMessage);
    }

    return response.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// Рендеринг UI
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Обновляет шкалу выживания: ширину полоски и числовое значение.
 * Добавляет CSS-класс "critical" при низком значении.
 *
 * @param {HTMLElement} bar   - Элемент заполнения шкалы
 * @param {HTMLElement} label - Элемент числового значения
 * @param {number}      value - Новое значение [0..100]
 */
function updateStatBar(bar, label, value) {
    const clamped = Math.max(0, Math.min(100, value));
    bar.style.width = clamped + "%";
    label.textContent = clamped;

    if (clamped <= CONFIG.CRITICAL_THRESHOLD) {
        bar.classList.add("critical");
    } else {
        bar.classList.remove("critical");
    }
}

/**
 * Обновляет все три шкалы выживания и прогресс-бар одновременно.
 *
 * @param {object} scores          - {health, warmth, satiety}
 * @param {number} questionNumber  - Номер текущего вопроса
 * @param {number} totalQuestions  - Всего вопросов
 */
function renderStats(scores, questionNumber = 0, totalQuestions = 0) {
    updateStatBar(DOM.healthBar,  DOM.healthValue,  scores.health);
    updateStatBar(DOM.warmthBar,  DOM.warmthValue,  scores.warmth);
    updateStatBar(DOM.satietyBar, DOM.satietyValue, scores.satiety);

    if (totalQuestions > 0) {
        const progressPct = Math.round((questionNumber / totalQuestions) * 100);
        DOM.progressBar.style.width = progressPct + "%";
        DOM.progressText.textContent = `${questionNumber}/${totalQuestions}`;
    }
}

/**
 * Отрисовывает карточку вопроса с вариантами ответов.
 *
 * @param {object} questionData - Данные вопроса от сервера
 */
function renderQuestion(questionData) {
    // Обновляем текст вопроса
    DOM.questionHintIcon.textContent = questionData.image_hint || "🌲";
    DOM.questionText.textContent = questionData.text || questionData.next_question_text;

    // Обновляем категорию в боковой панели
    const category = questionData.category || questionData.next_question_category;
    if (category) {
        DOM.categoryText.textContent = category;
        // Выбираем иконку по категории
        DOM.categoryIcon.textContent = getCategoryIcon(category);
    }

    // Скрываем блок обратной связи
    DOM.feedbackBox.classList.add("hidden");
    DOM.btnNext.classList.add("hidden");

    // Генерируем кнопки ответов
    const answers = questionData.answers || questionData.next_answers || [];
    DOM.answersGrid.innerHTML = "";

    answers.forEach((answer) => {
        const btn = document.createElement("button");
        btn.className = "answer-btn";
        btn.dataset.answerId = answer.id;
        btn.onclick = () => app.submitAnswer(answer.id);
        btn.innerHTML = `
            <span class="answer-letter">${answer.id.toUpperCase()}</span>
            <span class="answer-text">${escapeHtml(answer.text)}</span>
        `;
        DOM.answersGrid.appendChild(btn);
    });
}

/**
 * Показывает результат ответа: выделяет кнопки, показывает фидбэк.
 *
 * @param {object}  result        - Ответ от сервера
 * @param {string}  chosenId      - ID выбранного ответа
 */
function renderAnswerFeedback(result, chosenId) {
    // Блокируем все кнопки и помечаем правильный/неправильный
    const allButtons = DOM.answersGrid.querySelectorAll(".answer-btn");
    allButtons.forEach((btn) => {
        btn.disabled = true;

        // Находим правильный ответ — он будет в следующем вопросе... нет.
        // Сервер не раскрывает is_correct явно для всех, только через result.is_correct.
        // Помечаем выбранный как верный или неверный.
        if (btn.dataset.answerId === chosenId) {
            btn.classList.add(result.is_correct ? "correct" : "wrong");
        }
    });

    // Показываем блок обратной связи
    DOM.feedbackBox.classList.remove("hidden");
    DOM.feedbackIcon.textContent = result.is_correct ? "✅" : "❌";
    DOM.feedbackText.textContent = result.feedback;

    // Задержка перед появлением кнопки "Далее"
    setTimeout(() => {
        if (!DOM.btnNext.classList.contains("hidden") === false) {
            DOM.btnNext.classList.remove("hidden");
        }
    }, CONFIG.FEEDBACK_DELAY_MS);
}

/**
 * Показывает финальный экран победы или поражения.
 *
 * @param {string} status     - "dead" | "rescued"
 * @param {object} scores     - Финальные показатели
 */
function renderGameOver(status, scores) {
    DOM.questionCard.classList.add("hidden");
    DOM.welcomeScreen.classList.add("hidden");
    DOM.gameOverScreen.classList.remove("hidden");

    const isRescued = status === "rescued";

    DOM.gameOverIcon.textContent = isRescued ? "🚁" : "💀";

    DOM.gameOverTitle.textContent = isRescued ? "Вы спасены!" : "Вы погибли";
    DOM.gameOverTitle.className = `game-over-title ${isRescued ? "rescued" : "dead"}`;

    DOM.gameOverText.textContent = isRescued
        ? "Поздравляем! Вы успешно выжили в тайге и дождались спасателей. Отличные знания!"
        : "Тайга оказалась сильнее. Неправильные решения привели к трагическому финалу. Попробуйте ещё раз!";

    // Финальные показатели
    DOM.finalStats.innerHTML = `
        <div class="final-stat-item">
            <span>❤️</span>
            <span class="final-stat-value">${scores.health}</span>
            <span>Здоровье</span>
        </div>
        <div class="final-stat-item">
            <span>🔥</span>
            <span class="final-stat-value">${scores.warmth}</span>
            <span>Тепло</span>
        </div>
        <div class="final-stat-item">
            <span>🍗</span>
            <span class="final-stat-value">${scores.satiety}</span>
            <span>Сытость</span>
        </div>
    `;
}

// ─────────────────────────────────────────────────────────────────────────────
// Вспомогательные функции
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Экранирует HTML-символы для безопасной вставки в innerHTML.
 *
 * @param {string} text - Исходный текст
 * @returns {string} Безопасный HTML
 */
function escapeHtml(text) {
    const div = document.createElement("div");
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}

/**
 * Возвращает эмодзи-иконку по названию категории вопроса.
 *
 * @param {string} category - Название категории
 * @returns {string} Эмодзи
 */
function getCategoryIcon(category) {
    const icons = {
        "Разведение огня":    "🔥",
        "Ориентирование":     "🧭",
        "Съедобные растения": "🫐",
        "Встреча с животными":"🐻",
        "Вода и гидратация":  "💧",
        "Постройка укрытия":  "🏕️",
        "Сигналы спасателям": "🚁",
        "Первая помощь":      "🩹",
    };
    return icons[category] || "🌲";
}

/**
 * Показывает всплывающее уведомление об ошибке.
 *
 * @param {string} message - Текст ошибки
 */
function showToast(message) {
    const toast = DOM.toast;
    toast.textContent = "⚠️ " + message;
    toast.classList.remove("hidden");

    setTimeout(() => {
        toast.classList.add("hidden");
    }, CONFIG.TOAST_DURATION_MS);
}

/**
 * Переключает видимость экранов.
 *
 * @param {"welcome"|"question"|"gameover"} screen - Какой экран показать
 */
function showScreen(screen) {
    DOM.welcomeScreen.classList.add("hidden");
    DOM.questionCard.classList.add("hidden");
    DOM.gameOverScreen.classList.add("hidden");

    if (screen === "welcome")  DOM.welcomeScreen.classList.remove("hidden");
    if (screen === "question") DOM.questionCard.classList.remove("hidden");
    if (screen === "gameover") DOM.gameOverScreen.classList.remove("hidden");
}

// ─────────────────────────────────────────────────────────────────────────────
// Основной объект приложения (публичный интерфейс)
// ─────────────────────────────────────────────────────────────────────────────

const app = {

    /**
     * Запускает новую игровую сессию.
     * Вызывается кнопкой "Начать выживание" и "Попробовать снова".
     */
    async startGame() {
        if (AppState.isLoading) return;

        AppState.isLoading = true;
        AppState.isWaitingForNext = false;
        AppState.sessionId = null;

        if (DOM.btnStart) {
            DOM.btnStart.textContent = "Загрузка...";
            DOM.btnStart.disabled = true;
        }

        try {
            const data = await apiPost(CONFIG.ENDPOINTS.START);

            // Сохраняем ID сессии для дальнейших запросов
            AppState.sessionId = data.session_id;

            // Инициализируем шкалы
            renderStats(
                { health: data.health, warmth: data.warmth, satiety: data.satiety },
                1,
                data.total_questions
            );

            // Отрисовываем первый вопрос
            renderQuestion({
                text: data.question_text,
                image_hint: data.image_hint,
                category: data.question_category,
                answers: data.answers,
            });

            // Показываем карточку вопроса
            showScreen("question");

        } catch (error) {
            console.error("Ошибка старта игры:", error);
            showToast("Не удалось начать игру: " + error.message);
            showScreen("welcome");
        } finally {
            AppState.isLoading = false;
            if (DOM.btnStart) {
                DOM.btnStart.textContent = "НАЧАТЬ ВЫЖИВАНИЕ";
                DOM.btnStart.disabled = false;
            }
        }
    },

    /**
     * Отправляет выбранный ответ на сервер и обрабатывает результат.
     *
     * @param {string} answerId - Буква варианта ответа ("a"/"b"/"c"/"d")
     */
    async submitAnswer(answerId) {
        if (AppState.isLoading || AppState.isWaitingForNext) return;
        if (!AppState.sessionId) {
            showToast("Сессия не найдена. Начните новую игру.");
            return;
        }

        AppState.isLoading = true;

        try {
            const result = await apiPost(CONFIG.ENDPOINTS.ANSWER, {
                session_id: AppState.sessionId,
                answer_id: answerId,
            });

            // Обновляем шкалы состояния
            renderStats(
                { health: result.health, warmth: result.warmth, satiety: result.satiety },
                result.question_number,
                result.total_questions
            );

            // Показываем результат ответа
            renderAnswerFeedback(result, answerId);

            // Проверяем статус игры
            if (result.game_status === "dead" || result.game_status === "rescued") {
                // Игра завершена — задержка для чтения фидбэка, затем финальный экран
                setTimeout(() => {
                    renderGameOver(result.game_status, {
                        health:  result.health,
                        warmth:  result.warmth,
                        satiety: result.satiety,
                    });
                }, 2200);

            } else if (result.next_question_text) {
                // Есть следующий вопрос — сохраняем данные, показываем кнопку
                AppState.currentAnswer = result;
                AppState.isWaitingForNext = true;

                setTimeout(() => {
                    DOM.btnNext.classList.remove("hidden");
                }, CONFIG.FEEDBACK_DELAY_MS);
            }

        } catch (error) {
            console.error("Ошибка отправки ответа:", error);
            showToast(error.message);
        } finally {
            AppState.isLoading = false;
        }
    },

    /**
     * Загружает и отображает следующий вопрос.
     * Вызывается кнопкой "СЛЕДУЮЩИЙ ВОПРОС →".
     */
    loadNextQuestion() {
        if (!AppState.isWaitingForNext || !AppState.currentAnswer) return;

        const result = AppState.currentAnswer;
        AppState.isWaitingForNext = false;
        AppState.currentAnswer = null;

        renderQuestion({
            text: result.next_question_text,
            image_hint: result.next_image_hint,
            category: result.next_question_category,
            answers: result.next_answers,
        });

        // Плавная анимация — перезапускаем fadeInUp
        DOM.questionCard.style.animation = "none";
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                DOM.questionCard.style.animation = "fadeInUp 0.4s ease";
            });
        });
    },
};

// ─────────────────────────────────────────────────────────────────────────────
// Инициализация при загрузке страницы
// ─────────────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    // Показываем экран приветствия
    showScreen("welcome");
    console.log("🌲 Выжить в Тайге — приложение инициализировано");
});