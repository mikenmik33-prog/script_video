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
  submitButton.textContent = disabled ? "Створення..." : "Створити відео";
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

  const voiceWarning = document.getElementById("result-voice-warning");
  if (result.silent_voice_count > 0) {
    voiceWarning.textContent =
      `⚠️ ${result.silent_voice_count} із ${script.scenes.length} сцен озвучено тишею ` +
      `(edge-tts не відповів) - перевірте аудіофайли нижче перед монтажем.`;
    voiceWarning.hidden = false;
  } else {
    voiceWarning.hidden = true;
  }

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
  result.scene_images.forEach((url, index) => {
    addFileLink(filesList, `Візуал сцени ${index + 1}`, url);
  });
  result.voice_files.forEach((url, index) => {
    addFileLink(filesList, `Аудіо сцени ${index + 1}`, url);
  });

  const sceneVideosList = document.getElementById("result-scene-videos");
  sceneVideosList.innerHTML = "";
  result.scene_images.forEach((imageUrl, index) => {
    const scene = script.scenes[index];
    sceneVideosList.appendChild(createSceneVideoCard(scene, imageUrl, jobId));
  });

  resultPanel.hidden = false;
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

// Оживлення окремої сцени рухом через fal.ai (image-to-video) -
// вибіркова платна дія для однієї конкретної сцени, лише за явним
// підтвердженням.
function createSceneVideoCard(scene, imageUrl, jobId) {
  const card = document.createElement("div");
  card.className = "test-scene-card";

  const header = document.createElement("h3");
  header.textContent = `Сцена ${scene.scene}`;
  card.appendChild(header);

  const img = document.createElement("img");
  img.className = "test-preview-image";
  img.src = imageUrl;
  card.appendChild(img);

  // Перегенерація картинки сцени - щоб виправити невдалий/невідповідний
  // темі результат ДО того, як з нього почнеться платне "Оживити сцену"
  // (image-to-video завжди починається саме з цієї картинки).
  const imagePromptLabel = document.createElement("label");
  imagePromptLabel.textContent = "Промт картинки (можна відредагувати):";
  card.appendChild(imagePromptLabel);

  const imagePromptInput = document.createElement("textarea");
  imagePromptInput.className = "test-prompt-input";
  imagePromptInput.value = scene.visual_prompt;
  imagePromptInput.rows = 3;
  card.appendChild(imagePromptInput);

  const regenerateButton = document.createElement("button");
  regenerateButton.type = "button";
  regenerateButton.className = "test-continue-button";
  regenerateButton.textContent = "🔄 Перегенерувати фото (fal.ai, платно)";
  card.appendChild(regenerateButton);

  const regenerateStatus = document.createElement("p");
  regenerateStatus.className = "test-status";
  card.appendChild(regenerateStatus);

  regenerateButton.addEventListener("click", async () => {
    regenerateButton.disabled = true;
    regenerateStatus.textContent = "Генеруємо нову картинку...";
    try {
      const response = await fetch("/api/regenerate-image", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: jobId,
          scene_number: scene.scene,
          visual_prompt: imagePromptInput.value,
        }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Не вдалося перегенерувати картинку");
      }
      const { image_url: newImageUrl } = await response.json();
      img.src = newImageUrl;
      imageUrl = newImageUrl;
      regenerateStatus.textContent = "Готово.";
    } catch (err) {
      regenerateStatus.textContent = `Помилка: ${err.message}`;
    } finally {
      regenerateButton.disabled = false;
    }
  });

  const promptLabel = document.createElement("label");
  promptLabel.textContent = "Промт для руху (можна дописати опис дії/камери):";
  card.appendChild(promptLabel);

  const promptInput = document.createElement("textarea");
  promptInput.className = "test-prompt-input";
  promptInput.value = scene.visual_prompt;
  promptInput.rows = 3;
  card.appendChild(promptInput);

  const button = document.createElement("button");
  button.type = "button";
  button.className = "test-continue-button danger-button";
  button.textContent = "🎬 Оживити сцену (fal.ai, платно)";
  card.appendChild(button);

  const statusText = document.createElement("p");
  statusText.className = "test-status";
  card.appendChild(statusText);

  const previewVideo = document.createElement("video");
  previewVideo.className = "test-preview-video";
  previewVideo.controls = true;
  previewVideo.hidden = true;
  card.appendChild(previewVideo);

  button.addEventListener("click", async () => {
    const confirmed = window.confirm("Це реально витратить платний баланс fal.ai. Продовжити?");
    if (!confirmed) return;

    button.disabled = true;
    statusText.textContent = "Завантажуємо картинку сцени...";
    try {
      const imageBlob = await (await fetch(imageUrl)).blob();
      const imageData = await blobToDataUrl(imageBlob);

      statusText.textContent = "Надсилаємо запит до fal.ai...";
      const response = await fetch("/api/video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_data: imageData, visual_prompt: promptInput.value }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Не вдалося запустити генерацію відео");
      }
      const { job_id: jobId } = await response.json();

      statusText.textContent = "fal.ai генерує відео (може тривати до 3 хв)...";
      const POLL_INTERVAL_MS = 4000;
      while (true) {
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
        const statusResponse = await fetch(`/api/video/${jobId}`);
        if (!statusResponse.ok) {
          throw new Error("Помилка при перевірці статусу");
        }
        const data = await statusResponse.json();
        if (data.status === "done") {
          previewVideo.src = data.video_url;
          previewVideo.hidden = false;
          statusText.textContent = "Відео готове!";
          break;
        }
        if (data.status === "error") {
          throw new Error(data.error || "fal.ai не повернув результат");
        }
      }
    } catch (err) {
      statusText.textContent = `Помилка: ${err.message}`;
    } finally {
      button.disabled = false;
    }
  });

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

async function handleFormSubmit(event) {
  event.preventDefault();
  clearFormError();
  resetStages();
  resultPanel.hidden = true;

  const formData = new FormData(form);
  const payload = {
    topic: formData.get("topic").trim(),
    duration: Number(formData.get("duration")),
    style: formData.get("style"),
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

// --- Популярні ідеї (з YouTube) ---

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
  ideasUpdated.textContent = data.source === "youtube"
    ? formatUpdatedAt(data.last_updated)
    : "Демо-ідеї (щоб бачити реальні тренди YouTube, додайте YOUTUBE_API_KEY)";

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

    const views = formatViews(idea.views);
    if (views) {
      const viewsEl = document.createElement("div");
      viewsEl.className = "idea-views";
      viewsEl.textContent = views;
      card.appendChild(viewsEl);
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
    const response = await fetch("/api/trending-ideas");
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
    const response = await fetch("/api/trending-ideas/refresh", { method: "POST" });
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

loadTrendingIdeas();
setInterval(loadTrendingIdeas, IDEAS_AUTO_REFRESH_MS);
