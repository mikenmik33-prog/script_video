// AI Video Generator - frontend логіка (без фреймворків).
// Відповідає за: відправку форми, опитування статусу задачі та
// відображення результату.

const STAGE_ICONS = {
  pending: "○",
  active: "→",
  done: "✓",
  error: "✗",
};

const POLL_INTERVAL_MS = 1000;

const form = document.getElementById("generate-form");
const topicInput = document.getElementById("topic");
const submitButton = document.getElementById("submit-button");
const formError = document.getElementById("form-error");
const stageListItems = document.querySelectorAll("#stage-list li");
const progressBarFill = document.getElementById("progress-bar-fill");
const progressPercent = document.getElementById("progress-percent");
const resultPanel = document.getElementById("result-panel");

const scriptReviewPanel = document.getElementById("script-review-panel");
const scriptReviewScenes = document.getElementById("script-review-scenes");
const approveScriptButton = document.getElementById("approve-script-button");
const scriptReviewStatus = document.getElementById("script-review-status");

const languageSelect = document.getElementById("language");
const languageSelectWrapper = document.getElementById("language-select");
const languageSelectTrigger = document.getElementById("language-select-trigger");
const languageSelectValue = languageSelectTrigger.querySelector(".custom-select-value");
const languageSelectOptions = languageSelectWrapper.querySelector(".custom-select-options");
const ideasList = document.getElementById("ideas-list");
const ideasUpdated = document.getElementById("ideas-updated");
const refreshIdeasButton = document.getElementById("refresh-ideas-button");

let pollTimerId = null;

function showFormError(message) {
  formError.textContent = message;
  formError.hidden = false;
}

function clearFormError() {
  formError.hidden = true;
  formError.textContent = "";
}

function setFormDisabled(disabled) {
  submitButton.disabled = disabled;
  submitButton.textContent = disabled ? "Створення..." : "Створити промт";
}

function resetStages() {
  stageListItems.forEach((item) => {
    item.classList.remove("done", "active", "error");
    item.querySelector(".stage-icon").textContent = STAGE_ICONS.pending;
  });
  progressBarFill.style.width = "0%";
  progressPercent.textContent = "0%";
}

function renderStages(stages, progress) {
  stageListItems.forEach((item) => {
    const stageName = item.dataset.stage;
    const status = stages[stageName] || "pending";
    item.classList.remove("done", "active", "error");
    if (status !== "pending") {
      item.classList.add(status);
    }
    item.querySelector(".stage-icon").textContent = STAGE_ICONS[status];
  });
  progressBarFill.style.width = `${progress}%`;
  // 3 знаки після коми - щоб відсоток було видно "живим" навіть під час
  // довгого етапу монтажу, а не завислим на одному цілому числі
  progressPercent.textContent = `${progress.toFixed(3)}%`;
}

function stopPolling() {
  if (pollTimerId !== null) {
    clearTimeout(pollTimerId);
    pollTimerId = null;
  }
}

// Скільки поспіль невдалих спроб опитування статусу допускаємо, перш ніж
// здатися - Render безкоштовного тарифу інколи примусово перезапускає
// процес (найчастіше саме під час важкого етапу монтажу), і на кілька
// секунд, поки контейнер піднімається заново, запити повертають 502 чи
// взагалі не доходять. Без цих повторних спроб користувач бачив голу
// помилку мережі одразу після першого ж такого збою, хоча за кілька
// секунд сервер знову відповідав.
const MAX_STATUS_POLL_FAILURES = 60; // ~60с при POLL_INTERVAL_MS=1000 - з запасом на холодний старт Render
let statusPollFailures = 0;

async function pollStatus(jobId) {
  try {
    const response = await fetch(`/api/status/${jobId}`);
    if (!response.ok) {
      throw new Error("Не вдалося отримати статус задачі");
    }
    statusPollFailures = 0;
    const status = await response.json();
    renderStages(status.stages, status.progress);

    if (status.status === "done") {
      stopPolling();
      await loadResult(jobId);
      setFormDisabled(false);
    } else if (status.status === "error") {
      stopPolling();
      showFormError(status.error || "Сталася помилка під час генерації відео");
      setFormDisabled(false);
    } else if (status.status === "script_review") {
      stopPolling();
      await loadScriptReview(jobId);
      setFormDisabled(false);
    } else {
      pollTimerId = setTimeout(() => pollStatus(jobId), POLL_INTERVAL_MS);
    }
  } catch (err) {
    statusPollFailures += 1;
    if (statusPollFailures >= MAX_STATUS_POLL_FAILURES) {
      stopPolling();
      showFormError("Сервер тимчасово недоступний. Спробуйте оновити сторінку за хвилину.");
      setFormDisabled(false);
    } else {
      pollTimerId = setTimeout(() => pollStatus(jobId), POLL_INTERVAL_MS);
    }
  }
}

async function loadResult(jobId) {
  const response = await fetch(`/api/result/${jobId}`);
  if (!response.ok) {
    throw new Error("Не вдалося завантажити результат");
  }
  const data = await response.json();
  renderResult(data, jobId);
}

function renderResult(data, jobId) {
  const { script, result } = data;

  document.getElementById("result-full-text").textContent = script.full_text;

  const fullTextUk = document.getElementById("result-full-text-uk");
  if (script.full_text_uk) {
    fullTextUk.textContent = `Переклад укр.: ${script.full_text_uk}`;
    fullTextUk.hidden = false;
  } else {
    fullTextUk.hidden = true;
  }

  const scenesList = document.getElementById("result-scenes");
  scenesList.innerHTML = "";
  script.scenes.forEach((scene) => {
    const li = document.createElement("li");
    li.textContent = `Сцена ${scene.scene} (${scene.duration}с): ${scene.voice_text}`;
    scenesList.appendChild(li);
  });

  const filesList = document.getElementById("result-files");
  filesList.innerHTML = "";
  addFileLink(filesList, "Сценарій (JSON)", result.script_url);
  addFileLink(filesList, "Субтитри (SRT)", result.subtitles_url);
  result.voice_files.forEach((url, index) => {
    addFileLink(filesList, `Аудіо сцени ${index + 1}`, url);
  });

  const scenePromptsList = document.getElementById("result-scene-prompts");
  scenePromptsList.innerHTML = "";
  script.scenes.forEach((scene) => {
    scenePromptsList.appendChild(createScenePromptCard(scene));
  });

  resultPanel.hidden = false;
}

// Картка сцени: детальний промт сцени + рекомендований промт руху
// камери, готові для копіювання в Google Flow (чи інший text-to-video
// інструмент) - застосунок сам ні картинки, ні відео не генерує.
function createScenePromptCard(scene) {
  const card = document.createElement("div");
  card.className = "test-scene-card";

  const header = document.createElement("h3");
  header.textContent = `Сцена ${scene.scene}`;
  card.appendChild(header);

  const characterNote = document.createElement("p");
  characterNote.textContent = scene.character_appears
    ? "🧑 Miki з'являється в цій сцені"
    : "— Miki в цій сцені немає";
  card.appendChild(characterNote);

  if (scene.flow_duration) {
    const durationNote = document.createElement("p");
    durationNote.textContent =
      `⏱ Оберіть тривалість ${scene.flow_duration}с у Google Flow ` +
      `(найближче до реальної озвучки ${scene.duration}с - Flow вміє лише 4/6/8с)`;
    card.appendChild(durationNote);
  }

  const promptLabel = document.createElement("label");
  promptLabel.textContent = "Детальний промт сцени (скопіюйте в Google Flow):";
  card.appendChild(promptLabel);

  const promptText = document.createElement("textarea");
  promptText.className = "test-prompt-input";
  promptText.value = scene.visual_prompt || "";
  promptText.rows = 4;
  promptText.readOnly = true;
  card.appendChild(promptText);

  const motionLabel = document.createElement("label");
  motionLabel.textContent = "Рекомендований промт руху камери (Gemini підібрав під дію сцени):";
  card.appendChild(motionLabel);

  const motionText = document.createElement("textarea");
  motionText.className = "test-prompt-input";
  motionText.value = scene.motion_prompt || "";
  motionText.rows = 4;
  motionText.readOnly = true;
  card.appendChild(motionText);

  const transitionLabel = document.createElement("label");
  transitionLabel.textContent = "Рекомендований перехід у наступну сцену (для монтажу):";
  card.appendChild(transitionLabel);

  const transitionText = document.createElement("textarea");
  transitionText.className = "test-prompt-input";
  transitionText.value = scene.transition_prompt || "";
  transitionText.rows = 3;
  transitionText.readOnly = true;
  card.appendChild(transitionText);

  return card;
}

function addFileLink(container, label, url) {
  const li = document.createElement("li");
  const a = document.createElement("a");
  a.href = url;
  // download - клік одразу зберігає файл (замість відкриття в новій
  // вкладці, де картинку/аудіо ще довелося б зберігати вручну). Ім'я
  // файлу беремо з самого URL (той самий origin, тому браузер не
  // ігнорує атрибут через cross-origin обмеження).
  a.download = url.split("/").pop();
  a.rel = "noopener";
  a.textContent = label;
  li.appendChild(a);
  container.appendChild(li);
}

// --- Етап 1: перегляд/редагування сценарію ДО генерації картинок ---

async function loadScriptReview(jobId) {
  const response = await fetch(`/api/script/${jobId}`);
  if (!response.ok) {
    throw new Error("Не вдалося завантажити сценарій");
  }
  const data = await response.json();
  renderScriptReview(data, jobId);
}

function renderScriptReview(data, jobId) {
  const { script } = data;

  const scriptReviewFullTextUk = document.getElementById("script-review-full-text-uk");
  if (script.full_text_uk) {
    scriptReviewFullTextUk.textContent = `Переклад укр.: ${script.full_text_uk}`;
    scriptReviewFullTextUk.hidden = false;
  } else {
    scriptReviewFullTextUk.hidden = true;
  }

  scriptReviewScenes.innerHTML = "";
  script.scenes.forEach((scene) => {
    const card = document.createElement("div");
    card.className = "test-scene-card";

    const header = document.createElement("h3");
    header.textContent = `Сцена ${scene.scene} (${scene.duration}с)`;
    card.appendChild(header);

    const characterNote = document.createElement("p");
    characterNote.textContent = scene.character_appears
      ? "🧑 Miki з'являється в цій сцені"
      : "— Miki в цій сцені немає";
    card.appendChild(characterNote);

    const label = document.createElement("label");
    label.textContent = "Текст репліки:";
    card.appendChild(label);

    const textarea = document.createElement("textarea");
    textarea.className = "test-prompt-input";
    textarea.rows = 3;
    textarea.value = scene.voice_text;
    textarea.dataset.scene = scene.scene;
    textarea.dataset.field = "voice_text";
    card.appendChild(textarea);

    if (scene.translation_uk) {
      const translationNote = document.createElement("p");
      translationNote.className = "translation-note";
      translationNote.textContent = `Переклад укр.: ${scene.translation_uk}`;
      card.appendChild(translationNote);
    }

    const promptLabel = document.createElement("label");
    promptLabel.textContent = "Детальний промт сцени (для Google Flow):";
    card.appendChild(promptLabel);

    const promptTextarea = document.createElement("textarea");
    promptTextarea.className = "test-prompt-input";
    promptTextarea.rows = 3;
    promptTextarea.value = scene.visual_prompt;
    promptTextarea.dataset.scene = scene.scene;
    promptTextarea.dataset.field = "visual_prompt";
    card.appendChild(promptTextarea);

    scriptReviewScenes.appendChild(card);
  });

  scriptReviewStatus.hidden = true;
  scriptReviewStatus.textContent = "";
  approveScriptButton.disabled = false;
  scriptReviewPanel.hidden = false;
  approveScriptButton.onclick = () => handleApproveScript(jobId);
}

async function handleApproveScript(jobId) {
  const scenesByNumber = {};
  scriptReviewScenes.querySelectorAll("textarea").forEach((textarea) => {
    const sceneNumber = Number(textarea.dataset.scene);
    if (!scenesByNumber[sceneNumber]) {
      scenesByNumber[sceneNumber] = { scene: sceneNumber, voice_text: "", visual_prompt: "" };
    }
    scenesByNumber[sceneNumber][textarea.dataset.field] = textarea.value;
  });

  approveScriptButton.disabled = true;
  scriptReviewStatus.hidden = false;
  scriptReviewStatus.textContent = "Затверджуємо сценарій, готуємо фінальні файли...";
  try {
    const response = await fetch(`/api/script/${jobId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenes: Object.values(scenesByNumber) }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Не вдалося затвердити сценарій");
    }
    scriptReviewPanel.hidden = true;
    resetStages();
    pollStatus(jobId);
  } catch (err) {
    scriptReviewStatus.textContent = `Помилка: ${err.message}`;
    approveScriptButton.disabled = false;
  }
}

async function handleFormSubmit(event) {
  event.preventDefault();
  clearFormError();
  resetStages();
  resultPanel.hidden = true;
  scriptReviewPanel.hidden = true;

  const formData = new FormData(form);
  const payload = {
    topic: formData.get("topic").trim(),
    language: formData.get("language"),
  };

  if (!payload.topic) {
    showFormError("Введіть тему відео");
    return;
  }

  setFormDisabled(true);

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}));
      throw new Error(errorBody.detail || "Не вдалося запустити генерацію");
    }

    const { job_id: jobId } = await response.json();
    pollStatus(jobId);
  } catch (err) {
    showFormError(err.message);
    setFormDisabled(false);
  }
}

form.addEventListener("submit", handleFormSubmit);

// --- Ідеї для відео від Gemini ---

const IDEAS_AUTO_REFRESH_MS = 5 * 60 * 1000; // 5 хвилин

function formatViews(views) {
  if (views === null || views === undefined) return null;
  // точна кількість переглядів з розділювачами розрядів (напр. "1 234 567"),
  // а не скорочено - користувач попросив саме реальне число
  return `${views.toLocaleString("uk-UA")} переглядів`;
}

function formatUpdatedAt(unixSeconds) {
  if (!unixSeconds) return "";
  const date = new Date(unixSeconds * 1000);
  return `Оновлено о ${date.toLocaleTimeString("uk-UA", { hour: "2-digit", minute: "2-digit" })}`;
}

function renderIdeas(data) {
  const ideas = data.ideas || [];
  ideasUpdated.textContent = data.error || formatUpdatedAt(data.last_updated);

  if (ideas.length === 0) {
    ideasList.innerHTML = '<p class="ideas-loading">Ідей поки немає.</p>';
    return;
  }

  ideasList.innerHTML = "";
  ideas.forEach((idea, index) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "idea-card";

    const rank = document.createElement("div");
    rank.className = "idea-rank";
    rank.textContent = `#${index + 1}`;
    card.appendChild(rank);

    if (idea.thumbnail) {
      const img = document.createElement("img");
      img.className = "idea-thumbnail";
      img.src = idea.thumbnail;
      img.alt = "";
      card.appendChild(img);
    }

    const title = document.createElement("div");
    title.className = "idea-title";
    title.textContent = idea.title;
    card.appendChild(title);

    if (idea.hook) {
      const hook = document.createElement("div");
      hook.className = "idea-hook";
      hook.textContent = idea.hook;
      card.appendChild(hook);
    }

    card.addEventListener("click", () => {
      topicInput.value = idea.title;
      topicInput.focus();
    });

    ideasList.appendChild(card);
  });
}

async function loadTrendingIdeas() {
  try {
    const response = await fetch(`/api/trending-ideas?language=${languageSelect.value}`);
    if (!response.ok) return;
    const data = await response.json();
    renderIdeas(data);
  } catch (err) {
    // тихо ігноруємо - це не критична для роботи форми функція
  }
}

async function handleRefreshIdeas() {
  refreshIdeasButton.disabled = true;
  try {
    const response = await fetch(`/api/trending-ideas/refresh?language=${languageSelect.value}`, { method: "POST" });
    if (response.ok) {
      renderIdeas(await response.json());
    }
  } catch (err) {
    // тихо ігноруємо
  } finally {
    refreshIdeasButton.disabled = false;
  }
}

refreshIdeasButton.addEventListener("click", handleRefreshIdeas);
// Список ідей залежить від мови (окремі кеші uk/en на бекенді) -
// перемикання мови одразу показує вже підготовлений список тієї мови
// (без нового звернення до Gemini - лише читання кешу).
languageSelect.addEventListener("change", loadTrendingIdeas);

// Кастомний дропдаун мови: керує лише виглядом, а фактичне значення
// завжди зберігається в схованому нативному <select id="language">,
// тому решта коду (відправка форми, запити трендів) працює без змін.
function syncLanguageOptionUi(value) {
  const option = languageSelectOptions.querySelector(`li[data-value="${value}"]`);
  if (!option) return;

  languageSelectValue.textContent = option.textContent;
  languageSelectOptions.querySelectorAll("li").forEach((li) => {
    const isActive = li.dataset.value === value;
    li.classList.toggle("is-active", isActive);
    li.setAttribute("aria-selected", String(isActive));
  });
}

function selectLanguageOption(value) {
  syncLanguageOptionUi(value);
  languageSelect.value = value;
  languageSelect.dispatchEvent(new Event("change"));
}

function closeLanguageOptions() {
  languageSelectOptions.hidden = true;
  languageSelectTrigger.setAttribute("aria-expanded", "false");
}

function openLanguageOptions() {
  languageSelectOptions.hidden = false;
  languageSelectTrigger.setAttribute("aria-expanded", "true");
}

languageSelectTrigger.addEventListener("click", () => {
  if (languageSelectOptions.hidden) {
    openLanguageOptions();
  } else {
    closeLanguageOptions();
  }
});

languageSelectOptions.addEventListener("click", (event) => {
  const option = event.target.closest("li[data-value]");
  if (!option) return;
  selectLanguageOption(option.dataset.value);
  closeLanguageOptions();
});

document.addEventListener("click", (event) => {
  if (!languageSelectWrapper.contains(event.target)) {
    closeLanguageOptions();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeLanguageOptions();
  }
});

syncLanguageOptionUi(languageSelect.value);

loadTrendingIdeas();
setInterval(loadTrendingIdeas, IDEAS_AUTO_REFRESH_MS);
