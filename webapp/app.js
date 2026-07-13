"use strict";

/**
 * LiftMate Web App — выбор упражнения.
 *
 * Карточка конкретного упражнения (экран "exercise-detail") получает реальные данные
 * с API-сервера (api.py): последний результат и историю для графика прогресса.
 * Добавление своего упражнения пока остаётся заглушкой (console.log) — это следующий шаг.
 */

// Адрес задеплоенного API-сервера (см. api.py). Авторизация — Telegram initData
// в заголовке Authorization: Bearer <initData>, сервер сам проверяет подпись.
const API_BASE_URL = "https://liftmate-production-f659.up.railway.app";

// ---------------------------------------------------------------------------
// Данные упражнений — зеркало exercises_data.py (категории/упражнения/языки ru-en-fr)
// ---------------------------------------------------------------------------

const EXERCISE_CATEGORIES = {
  chest: {
    icon: "🎽",
    name: { ru: "Грудь", en: "Chest", fr: "Poitrine" },
    exercises: [
      { key: "bench_press", ru: "жим лёжа", en: "bench press", fr: "développé couché" },
      { key: "dumbbell_press", ru: "жим гантелей", en: "dumbbell press", fr: "développé couché haltères" },
      { key: "dumbbell_flyes", ru: "разводка гантелей", en: "dumbbell flyes", fr: "écarté couché haltères" },
      { key: "machine_chest_press", ru: "жим в тренажёре", en: "machine chest press", fr: "développé à la machine" },
    ],
  },
  back: {
    icon: "🦾",
    name: { ru: "Спина", en: "Back", fr: "Dos" },
    exercises: [
      { key: "barbell_row", ru: "тяга штанги в наклоне", en: "bent-over barbell row", fr: "rowing barre buste penché" },
      { key: "lat_pulldown", ru: "тяга блока", en: "lat pulldown", fr: "tirage vertical" },
      { key: "one_arm_dumbbell_row", ru: "тяга гантели одной рукой", en: "one-arm dumbbell row", fr: "rowing haltère à un bras" },
      { key: "deadlift", ru: "становая тяга", en: "deadlift", fr: "soulevé de terre" },
    ],
  },
  legs: {
    icon: "🦵",
    name: { ru: "Ноги", en: "Legs", fr: "Jambes" },
    exercises: [
      { key: "barbell_squat", ru: "присед со штангой", en: "barbell squat", fr: "squat à la barre" },
      { key: "leg_press", ru: "жим ногами", en: "leg press", fr: "presse à cuisses" },
      { key: "lunges", ru: "выпады", en: "lunges", fr: "fentes" },
      { key: "romanian_deadlift", ru: "румынская тяга", en: "romanian deadlift", fr: "soulevé de terre roumain" },
    ],
  },
  shoulders: {
    icon: "🤷",
    name: { ru: "Плечи", en: "Shoulders", fr: "Épaules" },
    exercises: [
      { key: "standing_barbell_press", ru: "жим штанги стоя", en: "standing barbell press", fr: "développé militaire debout" },
      { key: "seated_dumbbell_press", ru: "жим гантелей сидя", en: "seated dumbbell press", fr: "développé haltères assis" },
      { key: "lateral_raises", ru: "махи гантелями в стороны", en: "lateral raises", fr: "élévations latérales" },
    ],
  },
  biceps: {
    icon: "💪",
    name: { ru: "Бицепс", en: "Biceps", fr: "Biceps" },
    exercises: [
      { key: "barbell_curl", ru: "подъём штанги на бицепс", en: "barbell curl", fr: "curl à la barre" },
      { key: "dumbbell_curl", ru: "подъём гантелей на бицепс", en: "dumbbell curl", fr: "curl haltères" },
      { key: "hammer_curl", ru: "молотки", en: "hammer curl", fr: "curl marteau" },
    ],
  },
  triceps: {
    icon: "🥊",
    name: { ru: "Трицепс", en: "Triceps", fr: "Triceps" },
    exercises: [
      { key: "skull_crushers", ru: "французский жим", en: "skull crushers", fr: "extension triceps à la barre" },
      { key: "cable_pushdown", ru: "разгибания на блоке", en: "cable pushdown", fr: "extension à la poulie" },
      { key: "dips", ru: "отжимания на брусьях", en: "dips", fr: "dips" },
    ],
  },
};

// Тексты интерфейса на трёх языках (аналог локализованных строк в keyboards.py)
const UI_TEXT = {
  appTitle: { ru: "LiftMate", en: "LiftMate", fr: "LiftMate" },
  categoriesTitle: { ru: "Категории", en: "Categories", fr: "Catégories" },
  exercisesTitleFallback: { ru: "Упражнения", en: "Exercises", fr: "Exercices" },
  addCustom: {
    ru: "Добавить своё упражнение",
    en: "Add your own exercise",
    fr: "Ajouter mon exercice",
  },
  customFormTitle: { ru: "Своё упражнение", en: "Your own exercise", fr: "Ton exercice" },
  customFormLabel: { ru: "Название упражнения", en: "Exercise name", fr: "Nom de l'exercice" },
  customFormPlaceholder: {
    ru: "Например, кабельный кроссовер",
    en: "e.g. cable crossover",
    fr: "ex. : poulie vis-à-vis",
  },
  save: { ru: "Сохранить", en: "Save", fr: "Enregistrer" },
  back: { ru: "Назад", en: "Back", fr: "Retour" },
  tapToViewHint: {
    ru: "Нажми, чтобы увидеть прогресс",
    en: "Tap to see your progress",
    fr: "Appuie pour voir ta progression",
  },
  loadingText: { ru: "Загрузка…", en: "Loading…", fr: "Chargement…" },
  noDataText: {
    ru: "Пока нет данных — запиши первую тренировку!",
    en: "No data yet — log your first workout!",
    fr: "Pas encore de données — enregistre ton premier entraînement !",
  },
  errorText: {
    ru: "Не получилось загрузить данные. Попробуй ещё раз чуть позже.",
    en: "Couldn't load the data. Please try again in a bit.",
    fr: "Impossible de charger les données. Réessaie un peu plus tard.",
  },
  notInTelegramText: {
    ru: "Открой это меню внутри Telegram, чтобы увидеть свои данные.",
    en: "Open this menu inside Telegram to see your data.",
    fr: "Ouvre ce menu dans Telegram pour voir tes données.",
  },
  lastResultLabel: {
    ru: "Последний результат",
    en: "Last result",
    fr: "Dernier résultat",
  },
  progressLabel: { ru: "Прогресс", en: "Progress", fr: "Progression" },
  programNavLabel: { ru: "Программа", en: "Program", fr: "Programme" },
  programTitle: { ru: "Программа тренировки", en: "Workout program", fr: "Programme d'entraînement" },
  programEmptyText: {
    ru: "У тебя пока нет сохранённой программы.",
    en: "You don't have a saved program yet.",
    fr: "Tu n'as pas encore de programme enregistré.",
  },
  programCreateButtonLabel: { ru: "Создать программу", en: "Create a program", fr: "Créer un programme" },
  programCreateHintText: {
    ru: "Напиши боту /program, чтобы я её составил.",
    en: "Message the bot /program and I'll put one together.",
    fr: "Écris /program au bot pour que je t'en prépare un.",
  },
  programUnlockButtonLabel: {
    ru: "🔓 Разблокировать полную программу",
    en: "🔓 Unlock the full program",
    fr: "🔓 Débloquer le programme complet",
  },
  programComingSoonText: {
    ru: "Скоро будет доступно!",
    en: "Coming soon!",
    fr: "Bientôt disponible !",
  },
  programExportButtonLabel: {
    ru: "📄 Экспортировать как документ",
    en: "📄 Export as document",
    fr: "📄 Exporter en document",
  },
};

// Язык интерфейса: подтягивается из настроек пользователя в боте (/language,
// см. GET /api/user/{user_id}/settings) в detectUserLanguage() при старте — до
// того, как это разрешится, и в случае любой ошибки используем русский по
// умолчанию, чтобы интерфейс никогда не оставался без текста
let currentLanguage = "ru";

function pickLanguage(language) {
  const lang = (language || "en").toLowerCase();
  if (lang.startsWith("ru")) return "ru";
  if (lang.startsWith("fr")) return "fr";
  return "en";
}

function t(dict) {
  const lang = pickLanguage(currentLanguage);
  return dict[lang] || dict.en;
}

function exerciseName(exercise) {
  const lang = pickLanguage(currentLanguage);
  return exercise[lang] || exercise.en;
}

// ---------------------------------------------------------------------------
// Telegram Web App SDK: тема, готовность, разворачивание на весь экран
// ---------------------------------------------------------------------------

const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

// Палитра LiftMate фиксирована брендбуком (только лайм + оттенки серого/чёрного/
// белого) — в отличие от произвольных цветов Telegram.WebApp.themeParams, здесь
// нужно только определить, тёмная сейчас тема или светлая, а сами цвета для
// каждой темы уже прописаны в style.css как CSS-переменные.
const prefersLightScheme = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;

function detectColorScheme() {
  // Явный выбор пользователя в Telegram — приоритетнее системной настройки браузера
  if (tg && tg.colorScheme) {
    return tg.colorScheme; // "light" | "dark"
  }
  if (prefersLightScheme && prefersLightScheme.matches) {
    return "light";
  }
  return "dark";
}

function applyColorScheme() {
  document.documentElement.setAttribute("data-theme", detectColorScheme());
}

function initTelegram() {
  applyColorScheme();

  // Вне Telegram (например, в браузере при разработке) реагируем на смену
  // системной темы через prefers-color-scheme
  if (prefersLightScheme) {
    prefersLightScheme.addEventListener("change", applyColorScheme);
  }

  if (!tg) {
    return;
  }

  tg.ready();
  tg.expand();
  tg.onEvent("themeChanged", applyColorScheme);

  // Нативная кнопка "Назад" Telegram дублирует поведение кнопки в шапке —
  // приятнее для пользователя, чем полагаться только на кастомную кнопку
  tg.BackButton.onClick(() => goBack());
}

// ---------------------------------------------------------------------------
// API-сервер: получение user_id/initData и запросы к /last и /history
// ---------------------------------------------------------------------------

function getTelegramUserId() {
  // initDataUnsafe — это удобный, но НЕ проверенный на клиенте разбор initData
  // (сам Telegram его не подписывает отдельно). Здесь он нужен только чтобы
  // подставить user_id в URL — настоящая проверка личности происходит на сервере
  // через initData (сырую строку) в заголовке Authorization, см. getInitData()
  if (tg && tg.initDataUnsafe && tg.initDataUnsafe.user) {
    return tg.initDataUnsafe.user.id;
  }
  return null;
}

function getInitData() {
  return tg ? tg.initData : "";
}

async function fetchFromApi(path) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      Authorization: `Bearer ${getInitData()}`,
    },
  });

  if (!response.ok) {
    const error = new Error(`API ${path} вернул ${response.status}`);
    error.status = response.status;
    throw error;
  }

  return response.json();
}

function fetchExerciseLast(userId, exerciseName) {
  return fetchFromApi(`/api/user/${userId}/exercises/${encodeURIComponent(exerciseName)}/last`);
}

function fetchExerciseHistory(userId, exerciseName) {
  return fetchFromApi(`/api/user/${userId}/exercises/${encodeURIComponent(exerciseName)}/history`);
}

function fetchUserSettings(userId) {
  return fetchFromApi(`/api/user/${userId}/settings`);
}

function fetchLatestProgram(userId) {
  return fetchFromApi(`/api/user/${userId}/program/latest`);
}

// Язык интерфейса синхронизирован с ботом: пользователь один раз выбирает его
// командой /language в чате, а Web App при каждом открытии подтягивает тот же
// выбор — отдельного переключателя языка внутри приложения нет.
async function detectUserLanguage() {
  const userId = getTelegramUserId();
  if (!userId) {
    // Открыто вне Telegram (например, в браузере при разработке) — user_id
    // взять неоткуда, поэтому используем язык по умолчанию
    return "ru";
  }

  try {
    const settings = await fetchUserSettings(userId);
    if (settings && settings.language) {
      return pickLanguage(settings.language);
    }
  } catch (error) {
    console.error("Не удалось получить язык пользователя, использую русский по умолчанию:", error);
  }

  // Пользователь ещё ни разу не вызывал /language в боте (settings.language === null)
  // либо запрос не удался — в обоих случаях просто остаёмся на русском
  return "ru";
}

// ---------------------------------------------------------------------------
// Навигация между экранами
// ---------------------------------------------------------------------------

const screenElements = {
  categories: document.getElementById("screen-categories"),
  exercises: document.getElementById("screen-exercises"),
  "custom-form": document.getElementById("screen-custom-form"),
  "exercise-detail": document.getElementById("screen-exercise-detail"),
  program: document.getElementById("screen-program"),
};

const backButton = document.getElementById("backButton");
const screenTitleEl = document.getElementById("screenTitle");

// Стек экранов для кнопки "Назад": всегда начинаем с категорий
let screenStack = ["categories"];
// Категория, для которой сейчас открыт список упражнений / форма своего упражнения
let activeCategoryKey = null;
// Упражнение, открытое на экране "exercise-detail" (объект из EXERCISE_CATEGORIES)
let activeExercise = null;

function currentScreen() {
  return screenStack[screenStack.length - 1];
}

function renderHeader() {
  const screen = currentScreen();

  if (screen === "categories") {
    screenTitleEl.textContent = t(UI_TEXT.appTitle);
    backButton.hidden = true;
  } else if (screen === "exercises") {
    const category = activeCategoryKey ? EXERCISE_CATEGORIES[activeCategoryKey] : null;
    screenTitleEl.textContent = category ? t(category.name) : t(UI_TEXT.exercisesTitleFallback);
    backButton.hidden = false;
  } else if (screen === "custom-form") {
    screenTitleEl.textContent = t(UI_TEXT.customFormTitle);
    backButton.hidden = false;
  } else if (screen === "exercise-detail") {
    screenTitleEl.textContent = activeExercise ? exerciseName(activeExercise) : t(UI_TEXT.exercisesTitleFallback);
    backButton.hidden = false;
  } else if (screen === "program") {
    screenTitleEl.textContent = t(UI_TEXT.programTitle);
    backButton.hidden = false;
  }

  if (tg) {
    if (backButton.hidden) {
      tg.BackButton.hide();
    } else {
      tg.BackButton.show();
    }
  }
}

function showScreen(name, { push = true } = {}) {
  const previousName = currentScreen();
  const previousEl = screenElements[previousName];
  const nextEl = screenElements[name];

  if (previousEl && previousEl !== nextEl) {
    previousEl.classList.add("screen--leaving");
    previousEl.classList.remove("screen--active");
    window.setTimeout(() => previousEl.classList.remove("screen--leaving"), 300);
  }

  nextEl.classList.add("screen--active");

  if (push) {
    screenStack.push(name);
  }

  renderHeader();
}

function goBack() {
  if (screenStack.length <= 1) {
    return;
  }
  screenStack.pop();
  const target = currentScreen();

  Object.values(screenElements).forEach((el) => el.classList.remove("screen--active"));
  screenElements[target].classList.add("screen--active");

  if (target === "categories") {
    activeCategoryKey = null;
  }
  if (target !== "exercise-detail") {
    activeExercise = null;
  }

  renderHeader();
}

backButton.addEventListener("click", goBack);

// ---------------------------------------------------------------------------
// Экран 1: рендер сетки категорий
// ---------------------------------------------------------------------------

function renderCategories() {
  const grid = document.getElementById("categoryGrid");
  grid.innerHTML = "";

  Object.entries(EXERCISE_CATEGORIES).forEach(([categoryKey, category]) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "category-card";
    card.innerHTML = `
      <span class="category-card__icon" aria-hidden="true">${category.icon}</span>
      <span class="category-card__name">${t(category.name)}</span>
    `;
    card.addEventListener("click", () => openCategory(categoryKey));
    grid.appendChild(card);
  });
}

function openCategory(categoryKey) {
  activeCategoryKey = categoryKey;
  renderExercises(categoryKey);
  showScreen("exercises");
}

// ---------------------------------------------------------------------------
// Экран 2: рендер списка упражнений выбранной категории
// ---------------------------------------------------------------------------

function renderExercises(categoryKey) {
  const category = EXERCISE_CATEGORIES[categoryKey];
  const list = document.getElementById("exerciseList");
  list.innerHTML = "";

  category.exercises.forEach((exercise) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "exercise-card";
    card.innerHTML = `
      <span class="exercise-card__thumb" aria-hidden="true">🏋️</span>
      <span class="exercise-card__body">
        <span class="exercise-card__name">${exerciseName(exercise)}</span>
        <span class="exercise-card__last-result">${t(UI_TEXT.tapToViewHint)}</span>
      </span>
    `;
    card.addEventListener("click", () => openExerciseDetail(exercise));
    list.appendChild(card);
  });
}

// ---------------------------------------------------------------------------
// Экран 3: форма "Добавить своё упражнение"
// ---------------------------------------------------------------------------

function renderCustomForm() {
  document.getElementById("customFormLabel").textContent = t(UI_TEXT.customFormLabel);

  const input = document.getElementById("customExerciseInput");
  input.placeholder = t(UI_TEXT.customFormPlaceholder);
  input.value = "";

  document.getElementById("customFormSubmit").textContent = t(UI_TEXT.save);
}

document.getElementById("addCustomButton").addEventListener("click", () => {
  renderCustomForm();
  showScreen("custom-form");
});

document.getElementById("customExerciseForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = document.getElementById("customExerciseInput");
  const name = input.value.trim();

  if (!name) {
    return;
  }

  // Заглушка: реальное сохранение в custom_exercises подключим на следующем шаге
  console.log("Сохранить своё упражнение:", name, "категория:", activeCategoryKey);

  goBack();
});

// ---------------------------------------------------------------------------
// Экран 4: карточка упражнения — последний результат + график прогресса
// ---------------------------------------------------------------------------

function openExerciseDetail(exercise) {
  activeExercise = exercise;
  showScreen("exercise-detail");
  loadExerciseDetail(exercise);
}

function trimNumber(value) {
  // Аналог Python "{:g}" — убирает лишние нули после точки (80.0 -> "80", 82.5 -> "82.5")
  return Number(value).toString();
}

function pluralizeSetsRu(count) {
  const n = Math.abs(count) % 100;
  if (n >= 11 && n <= 14) return "подходов";
  const lastDigit = n % 10;
  if (lastDigit === 1) return "подход";
  if (lastDigit >= 2 && lastDigit <= 4) return "подхода";
  return "подходов";
}

function formatLastResult(entry) {
  const lang = pickLanguage(currentLanguage);
  const weight = trimNumber(entry.weight);

  if (lang === "ru") {
    return `${weight}кг × ${entry.reps}, ${entry.sets} ${pluralizeSetsRu(entry.sets)}`;
  }
  if (lang === "fr") {
    const setsWord = entry.sets === 1 ? "série" : "séries";
    return `${weight}kg × ${entry.reps}, ${entry.sets} ${setsWord}`;
  }
  const setsWord = entry.sets === 1 ? "set" : "sets";
  return `${weight}kg × ${entry.reps}, ${entry.sets} ${setsWord}`;
}

function formatShortDate(isoDate) {
  const [, month, day] = isoDate.split("-");
  return `${day}.${month}`;
}

function buildProgressChartSVG(history) {
  const width = 300;
  const height = 140;
  const paddingX = 30;
  const paddingY = 22;
  const innerWidth = width - paddingX * 2;
  const innerHeight = height - paddingY * 2;

  const weights = history.map((entry) => entry.weight);
  const minWeight = Math.min(...weights);
  const maxWeight = Math.max(...weights);
  const weightRange = maxWeight - minWeight || 1; // избегаем деления на 0, если все веса равны

  const points = history.map((entry, index) => {
    const x = history.length === 1
      ? paddingX + innerWidth / 2
      : paddingX + (index / (history.length - 1)) * innerWidth;
    const y = paddingY + innerHeight - ((entry.weight - minWeight) / weightRange) * innerHeight;
    return { x, y };
  });

  const polylinePoints = points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const circles = points
    .map((p) => `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3.5" fill="var(--accent-lime)" />`)
    .join("");

  const firstDate = formatShortDate(history[0].date);
  const lastDate = formatShortDate(history[history.length - 1].date);

  return `
    <svg viewBox="0 0 ${width} ${height}" class="progress-chart" role="img" aria-label="${t(UI_TEXT.progressLabel)}">
      <polyline points="${polylinePoints}" fill="none" stroke="var(--accent-lime)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
      ${circles}
      <text x="${paddingX}" y="${height - 4}" class="progress-chart__label">${firstDate}</text>
      <text x="${width - paddingX}" y="${height - 4}" class="progress-chart__label" text-anchor="end">${lastDate}</text>
      <text x="${paddingX - 6}" y="${paddingY + 4}" class="progress-chart__value-label" text-anchor="end">${trimNumber(maxWeight)}</text>
      <text x="${paddingX - 6}" y="${height - paddingY}" class="progress-chart__value-label" text-anchor="end">${trimNumber(minWeight)}</text>
    </svg>
  `;
}

async function loadExerciseDetail(exercise) {
  const container = document.getElementById("exerciseDetail");
  container.innerHTML = `<p class="exercise-detail__status">${t(UI_TEXT.loadingText)}</p>`;

  const userId = getTelegramUserId();
  if (!userId) {
    container.innerHTML = `<p class="exercise-detail__status">${t(UI_TEXT.notInTelegramText)}</p>`;
    return;
  }

  // Канонично на английском — так упражнение хранится в базе данных бота
  // (см. exercises_data.py: get_canonical_exercise_name), независимо от языка интерфейса
  const canonicalName = exercise.en;

  try {
    const [last, history] = await Promise.all([
      fetchExerciseLast(userId, canonicalName),
      fetchExerciseHistory(userId, canonicalName),
    ]);

    // Если открыт другой экран, пока запрос летал туда-обратно — не рендерим лишнее
    if (activeExercise !== exercise) {
      return;
    }

    if (!last || history.length === 0) {
      container.innerHTML = `<p class="exercise-detail__status">${t(UI_TEXT.noDataText)}</p>`;
      return;
    }

    container.innerHTML = `
      <div class="exercise-detail__section">
        <div class="exercise-detail__label">${t(UI_TEXT.lastResultLabel)}</div>
        <div class="exercise-detail__last-value">${formatLastResult(last)}</div>
      </div>
      <div class="exercise-detail__section">
        <div class="exercise-detail__label">${t(UI_TEXT.progressLabel)}</div>
        ${buildProgressChartSVG(history)}
      </div>
    `;
  } catch (error) {
    console.error("Не удалось загрузить данные упражнения:", error);
    if (activeExercise === exercise) {
      container.innerHTML = `<p class="exercise-detail__status">${t(UI_TEXT.errorText)}</p>`;
    }
  }
}

// ---------------------------------------------------------------------------
// Экран 5: программа тренировки (teaser — первые 2 упражнения открыты всем,
// остальные заблокированы/размыты для не-premium пользователей)
// ---------------------------------------------------------------------------

const FREE_EXERCISES_COUNT = 2;

function formatSetsReps(exercise) {
  // reps — строка: либо диапазон чисел ("8-10"), либо фраза вроде "до отказа"/"to failure" —
  // слово "повторений"/"reps" грамматически уместно только для числового диапазона
  const lang = pickLanguage(currentLanguage);
  const isNumericReps = /^\d+(\s*-\s*\d+)?$/.test(String(exercise.reps).trim());

  if (lang === "ru") {
    const repsPart = isNumericReps ? `${exercise.reps} повторений` : exercise.reps;
    return `${exercise.sets} ${pluralizeSetsRu(exercise.sets)} × ${repsPart}`;
  }
  if (lang === "fr") {
    const setsWord = exercise.sets === 1 ? "série" : "séries";
    const repsPart = isNumericReps ? `${exercise.reps} répétitions` : exercise.reps;
    return `${exercise.sets} ${setsWord} × ${repsPart}`;
  }
  const setsWord = exercise.sets === 1 ? "set" : "sets";
  const repsPart = isNumericReps ? `${exercise.reps} reps` : exercise.reps;
  return `${exercise.sets} ${setsWord} × ${repsPart}`;
}

function buildProgramExerciseCard(exercise, index, locked) {
  if (locked) {
    return `
      <div class="program-exercise-card program-exercise-card--locked">
        <div class="program-exercise-card__index">${index + 1}</div>
        <div class="program-exercise-card__body">
          <div class="program-exercise-card__name">${exercise.name}</div>
          <div class="program-exercise-card__locked-details">
            <div class="program-exercise-card__meta">${formatSetsReps(exercise)}</div>
            <div class="program-exercise-card__why">💡 ${exercise.why}</div>
          </div>
        </div>
        <div class="program-exercise-card__lock-badge" aria-hidden="true">🔒</div>
      </div>
    `;
  }

  return `
    <div class="program-exercise-card">
      <div class="program-exercise-card__index">${index + 1}</div>
      <div class="program-exercise-card__body">
        <div class="program-exercise-card__name">${exercise.name}</div>
        <div class="program-exercise-card__meta">${formatSetsReps(exercise)}</div>
        <div class="program-exercise-card__why">💡 ${exercise.why}</div>
      </div>
    </div>
  `;
}

function renderProgramEmpty(container) {
  container.innerHTML = `
    <div class="program-empty">
      <p class="program-empty__text">${t(UI_TEXT.programEmptyText)}</p>
      <p class="program-empty__hint">${t(UI_TEXT.programCreateHintText)}</p>
      <button class="program-create-button" id="programCreateButton" type="button">${t(UI_TEXT.programCreateButtonLabel)}</button>
    </div>
  `;
  document.getElementById("programCreateButton").addEventListener("click", () => {
    // Web App не может сама отправить команду в чат — лучшее, что можно сделать,
    // это закрыть Web App, чтобы пользователь вернулся в чат и написал /program сам
    if (tg) {
      tg.close();
    }
  });
}

function renderProgram(container, exercises, isPremium) {
  const cardsHtml = exercises
    .map((exercise, index) => buildProgramExerciseCard(exercise, index, !isPremium && index >= FREE_EXERCISES_COUNT))
    .join("");

  const actionButtonHtml = isPremium
    ? `<button class="program-export-button" id="programActionButton" type="button">${t(UI_TEXT.programExportButtonLabel)}</button>`
    : `<button class="program-unlock-button" id="programActionButton" type="button">${t(UI_TEXT.programUnlockButtonLabel)}</button>`;

  container.innerHTML = `
    <div class="program-exercise-list">${cardsHtml}</div>
    ${actionButtonHtml}
  `;

  document.getElementById("programActionButton").addEventListener("click", () => {
    // Реальная оплата/экспорт подключим позже — пока просто заглушка
    window.alert(t(UI_TEXT.programComingSoonText));
  });
}

async function loadProgramScreen() {
  const container = document.getElementById("programScreen");
  container.innerHTML = `<p class="exercise-detail__status">${t(UI_TEXT.loadingText)}</p>`;

  const userId = getTelegramUserId();
  if (!userId) {
    container.innerHTML = `<p class="exercise-detail__status">${t(UI_TEXT.notInTelegramText)}</p>`;
    return;
  }

  try {
    const data = await fetchLatestProgram(userId);

    // Пользователь мог уйти с экрана, пока запрос летал туда-обратно
    if (currentScreen() !== "program") {
      return;
    }

    if (!data.exercises || data.exercises.length === 0) {
      renderProgramEmpty(container);
      return;
    }

    renderProgram(container, data.exercises, Boolean(data.is_premium));
  } catch (error) {
    console.error("Не удалось загрузить программу тренировки:", error);
    if (currentScreen() === "program") {
      container.innerHTML = `<p class="exercise-detail__status">${t(UI_TEXT.errorText)}</p>`;
    }
  }
}

function openProgramScreen() {
  showScreen("program");
  loadProgramScreen();
}

document.getElementById("programNavButton").addEventListener("click", openProgramScreen);

// ---------------------------------------------------------------------------
// Инициализация
// ---------------------------------------------------------------------------

async function init() {
  initTelegram();

  // Ждём язык ДО первого рендера экранов, иначе пользователь на долю секунды
  // увидит русский интерфейс, даже если в боте выбран другой язык
  currentLanguage = await detectUserLanguage();

  document.getElementById("addCustomButtonLabel").textContent = t(UI_TEXT.addCustom);
  document.getElementById("programNavButtonLabel").textContent = t(UI_TEXT.programNavLabel);

  renderCategories();
  renderHeader();
}

document.addEventListener("DOMContentLoaded", () => {
  init();
});
