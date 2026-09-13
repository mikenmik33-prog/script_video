// Тестова панель промтів - окрема "лабораторія" для швидкої ітерації
// коротких сценаріїв і візуальних промтів, без повного циклу монтажу.

const scriptForm = document.getElementById("script-form");
const scriptSubmit = document.getElementById("script-submit");
const scriptError = document.getElementById("script-error");
const scenesPanel = document.getElementById("scenes-panel");
const scenesList = document.getElementById("scenes-list");

function showError(el, message) {
  el.textContent = message;
  el.hidden = false;
}

function clearError(el) {
  el.hidden = true;
  el.textContent = "";
}

function createSceneCard(scene, style) {
  const card = document.createElement("div");
  card.className = "test-scene-card";
  let lastImageData = null;

  const header = document.createElement("h3");
  header.textContent = `Сцена ${scene.scene} (${scene.duration}с, перехід: ${scene.transition})`;
  card.appendChild(header);

  const voiceFieldLabel = document.createElement("label");
  voiceFieldLabel.textContent = "Озвучка (можна редагувати):";
  card.appendChild(voiceFieldLabel);

  const voiceInput = document.createElement("textarea");
  voiceInput.className = "test-prompt-input";
  voiceInput.value = scene.voice_text;
  voiceInput.rows = 2;
  card.appendChild(voiceInput);

  const subtitleFieldLabel = document.createElement("label");
  subtitleFieldLabel.textContent = "Субтитр (можна редагувати):";
  card.appendChild(subtitleFieldLabel);

  const subtitleInput = document.createElement("textarea");
  subtitleInput.className = "test-prompt-input";
  subtitleInput.value = scene.subtitle;
  subtitleInput.rows = 2;
  card.appendChild(subtitleInput);

  const promptLabel = document.createElement("label");
  promptLabel.textContent = "Візуальний промт (можна редагувати):";
  card.appendChild(promptLabel);

  const promptInput = document.createElement("textarea");
  promptInput.className = "test-prompt-input";
  promptInput.value = scene.visual_prompt;
  promptInput.rows = 3;
  card.appendChild(promptInput);

  const buttonsRow = document.createElement("div");
  buttonsRow.className = "test-buttons-row";

  const imageButton = document.createElement("button");
  imageButton.type = "button";
  imageButton.textContent = "🖼 Перегенерувати картинку (безкоштовно)";
  buttonsRow.appendChild(imageButton);

  const videoButton = document.createElement("button");
  videoButton.type = "button";
  videoButton.className = "danger-button";
  videoButton.textContent = "🎬 Згенерувати відео (fal.ai, платно)";
  buttonsRow.appendChild(videoButton);

  card.appendChild(buttonsRow);

  const statusText = document.createElement("p");
  statusText.className = "test-status";
  card.appendChild(statusText);

  const previewImg = document.createElement("img");
  previewImg.className = "test-preview-image";
  previewImg.hidden = true;
  card.appendChild(previewImg);

  const previewVideo = document.createElement("video");
  previewVideo.className = "test-preview-video";
  previewVideo.controls = true;
  previewVideo.hidden = true;
  card.appendChild(previewVideo);

  imageButton.addEventListener("click", async () => {
    imageButton.disabled = true;
    statusText.textContent = "Генерується картинка...";
    try {
      const response = await fetch("/api/test/image", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ visual_prompt: promptInput.value, style }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Не вдалося згенерувати картинку");
      }
      const data = await response.json();
      // зберігаємо байти картинки в пам'яті браузера (не лише URL) -
      // якщо Render "засне" й перезапустить контейнер до натискання
      // "Згенерувати відео", файл на диску сервера може зникнути, а
      // ці дані нікуди не дінуться
      lastImageData = data.image_data;
      previewImg.src = `${data.image_url}?t=${Date.now()}`;
      previewImg.hidden = false;
      statusText.textContent = "Готово.";
    } catch (err) {
      statusText.textContent = `Помилка: ${err.message}`;
    } finally {
      imageButton.disabled = false;
    }
  });

  videoButton.addEventListener("click", async () => {
    if (!lastImageData) {
      statusText.textContent = "Спочатку згенеруйте картинку кнопкою вище.";
      return;
    }
    const confirmed = window.confirm(
      "Це реально витратить платний баланс fal.ai. Продовжити?"
    );
    if (!confirmed) return;

    videoButton.disabled = true;
    statusText.textContent = "Надсилаємо запит до fal.ai...";
    try {
      const response = await fetch("/api/test/video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_data: lastImageData, visual_prompt: promptInput.value }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || "Не вдалося запустити генерацію відео");
      }
      const { job_id: jobId } = await response.json();
      await pollVideoJob(jobId, statusText, previewVideo);
    } catch (err) {
      statusText.textContent = `Помилка: ${err.message}`;
    } finally {
      videoButton.disabled = false;
    }
  });

  return card;
}

async function pollVideoJob(jobId, statusText, previewVideo) {
  statusText.textContent = "fal.ai генерує відео (може тривати до 3 хв)...";
  const POLL_INTERVAL_MS = 4000;

  while (true) {
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));

    const response = await fetch(`/api/test/video/${jobId}`);
    if (!response.ok) {
      statusText.textContent = "Помилка при перевірці статусу.";
      return;
    }
    const data = await response.json();

    if (data.status === "done") {
      previewVideo.src = data.video_url;
      previewVideo.hidden = false;
      statusText.textContent = "Відео готове!";
      return;
    }
    if (data.status === "error") {
      statusText.textContent = `Помилка fal.ai: ${data.error}`;
      return;
    }
  }
}

async function handleScriptSubmit(event) {
  event.preventDefault();
  clearError(scriptError);
  scenesPanel.hidden = true;
  scenesList.innerHTML = "";

  const topic = document.getElementById("topic").value.trim();
  const duration = Number(document.getElementById("duration").value);
  const style = document.getElementById("style").value;
  const language = document.getElementById("language").value;

  if (!topic) {
    showError(scriptError, "Введіть тему");
    return;
  }

  scriptSubmit.disabled = true;
  scriptSubmit.textContent = "Генерація...";

  try {
    const response = await fetch("/api/test/script", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic, duration, language }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Не вдалося згенерувати сценарій");
    }
    const data = await response.json();
    data.script.scenes.forEach((scene) => {
      scenesList.appendChild(createSceneCard(scene, style));
    });
    scenesPanel.hidden = false;
  } catch (err) {
    showError(scriptError, err.message);
  } finally {
    scriptSubmit.disabled = false;
    scriptSubmit.textContent = "Згенерувати сценарій";
  }
}

scriptForm.addEventListener("submit", handleScriptSubmit);
