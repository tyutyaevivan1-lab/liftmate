"use strict";

/**
 * LiftMate Web App — выбор упражнения.
 * Чистый фронтенд без реальной интеграции с ботом: все действия (клик по упражнению,
 * сохранение своего упражнения) пока только логируются в консоль — реальная логика и
 * передача языка/данных пользователя будут подключены следующим шагом.
 */

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
  noResultPlaceholder: {
    // Статичный пример для дизайна — реальные данные подключим следующим шагом
    ru: "50кг × 10, 3 подхода",
    en: "50kg × 10, 3 sets",
    fr: "50kg × 10, 3 séries",
  },
};

// Язык интерфейса: пока всегда "ru" по умолчанию — реальная передача языка
// пользователя (из user_settings бэкенда) будет подключена следующим шагом
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
// Навигация между экранами
// ---------------------------------------------------------------------------

const screenElements = {
  categories: document.getElementById("screen-categories"),
  exercises: document.getElementById("screen-exercises"),
  "custom-form": document.getElementById("screen-custom-form"),
};

const backButton = document.getElementById("backButton");
const screenTitleEl = document.getElementById("screenTitle");

// Стек экранов для кнопки "Назад": всегда начинаем с категорий
let screenStack = ["categories"];
// Категория, для которой сейчас открыт список упражнений / форма своего упражнения
let activeCategoryKey = null;

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
        <span class="exercise-card__last-result">${t(UI_TEXT.noResultPlaceholder)}</span>
      </span>
    `;
    card.addEventListener("click", () => {
      // Заглушка: реальное сохранение подхода подключим на следующем шаге
      console.log("Выбрано упражнение:", exerciseName(exercise), exercise.key);
    });
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
// Инициализация
// ---------------------------------------------------------------------------

function init() {
  initTelegram();

  document.getElementById("addCustomButtonLabel").textContent = t(UI_TEXT.addCustom);

  renderCategories();
  renderHeader();
}

document.addEventListener("DOMContentLoaded", init);
