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

async function pollStatus(jobId) {
  try {
    const response = await fetch(`/api/status/${jobId}`);
    if (!response.ok) {
      throw new Error("Не вдалося отримати статус задачі");
    }
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
    stopPolling();
    showFormError(err.message);
    setFormDisabled(false);
  }
}

async function loadResult(jobId) {
  const response = await fetch(`/api/result/${jobId}`);
  if (!response.ok) {
    throw new Error("Не вдалося завантажити результат");
  }
  const data = await response.json();
  renderResult(data);
}

function renderResult(data) {
  const { script, result } = data;

  const video = document.getElementById("result-video");
  video.src = result.video_url;

  document.getElementById("result-full-text").textContent = script.full_text;

  const scenesList = document.getElementById("result-scenes");
  scenesList.innerHTML = "";
  script.scenes.forEach((scene) => {
    const li = document.createElement("li");
    li.textContent = `Сцена ${scene.scene} (${scene.duration}с): ${scene.voice_text}`;
    scenesList.appendChild(li);
  });

  const filesList = document.getElementById("result-files");
  filesList.innerHTML = "";
  addFileLink(filesList, "Готове відео (MP4)", result.video_url);
  addFileLink(filesList, "Сценарій (JSON)", result.script_url);
  addFileLink(filesList, "Субтитри (SRT)", result.subtitles_url);
  result.scene_images.forEach((url, index) => {
    addFileLink(filesList, `Візуал сцени ${index + 1}`, url);
  });
  result.voice_files.forEach((url, index) => {
    addFileLink(filesList, `Аудіо сцени ${index + 1}`, url);
  });

  resultPanel.hidden = false;
}

function addFileLink(container, label, url) {
  const li = document.createElement("li");
  const a = document.createElement("a");
  a.href = url;
  a.target = "_blank";
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
  if (views >= 1_000_000) return `${(views / 1_000_000).toFixed(1)}М переглядів`;
  if (views >= 1_000) return `${(views / 1_000).toFixed(1)}тис. переглядів`;
  return `${views} переглядів`;
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
