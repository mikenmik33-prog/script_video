// Тестова панель промтів - окрема "лабораторія" для швидкої ітерації
// коротких сценаріїв і візуальних промтів, без повного циклу монтажу.

const scriptForm = document.getElementById("script-form");
const scriptSubmit = document.getElementById("script-submit");
const scriptError = document.getElementById("script-error");
const scenesPanel = document.getElementById("scenes-panel");
const scenesList = document.getElementById("scenes-list");

const finalizePanel = document.getElementById("finalize-panel");
const finalizeButton = document.getElementById("finalize-button");
const finalizeError = document.getElementById("finalize-error");
const finalizeStatus = document.getElementById("finalize-status");
const finalizeVideo = document.getElementById("finalize-video");

function showError(el, message) {
  el.textContent = message;
  el.hidden = false;
}

function clearError(el) {
  el.hidden = true;
  el.textContent = "";
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

function createSceneCard(scene, style) {
  const card = document.createElement("div");
  card.className = "test-scene-card";
  let lastImageData = null;
  let lastVideoData = null;

  // Відео завжди прив'язане до КОНКРЕТНОЇ картинки, з якої його
  // згенерували - якщо картинка змінилась (перегенерована, завантажена
  // своя чи прибрана), старе відео вже не відповідає новому кадру і
  // його треба сховати, інакше можна випадково "фіналізувати" сцену зі
  // старим відео поверх нової картинки
  function resetVideoState() {
    lastVideoData = null;
    previewVideo.hidden = true;
    continueButton.hidden = true;
  }

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

  const imagesRow = document.createElement("div");
  imagesRow.className = "test-images-row";
  card.appendChild(imagesRow);

  const previewWrap = document.createElement("div");
  previewWrap.className = "test-preview-wrap";
  imagesRow.appendChild(previewWrap);

  const previewImg = document.createElement("img");
  previewImg.className = "test-preview-image";
  previewImg.hidden = true;
  previewWrap.appendChild(previewImg);

  const removeImageButton = document.createElement("button");
  removeImageButton.type = "button";
  removeImageButton.className = "test-remove-image-button";
  removeImageButton.textContent = "✕";
  removeImageButton.title = "Прибрати зображення";
  removeImageButton.hidden = true;
  previewWrap.appendChild(removeImageButton);

  removeImageButton.addEventListener("click", () => {
    lastImageData = null;
    previewImg.src = "";
    previewImg.hidden = true;
    removeImageButton.hidden = true;
    uploadInput.value = "";
    uploadZone.classList.remove("has-image");
    resetVideoState();
    statusText.textContent = "";
  });

  // Зона для перетягування власного зображення - якщо AI-генерація не
  // влаштовує, можна підставити своє фото як вихідний кадр для fal.ai
  // (те саме поле lastImageData, що й для згенерованої картинки)
  const uploadZone = document.createElement("label");
  uploadZone.className = "test-upload-zone";
  uploadZone.textContent = "Перетягніть своє зображення сюди\nабо натисніть, щоб обрати файл";

  const uploadInput = document.createElement("input");
  uploadInput.type = "file";
  uploadInput.accept = "image/*";
  uploadInput.hidden = true;
  uploadZone.appendChild(uploadInput);
  imagesRow.appendChild(uploadZone);

  function handleUploadedFile(file) {
    if (!file || !file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = () => {
      lastImageData = reader.result;
      previewImg.src = reader.result;
      previewImg.hidden = false;
      removeImageButton.hidden = false;
      uploadZone.classList.add("has-image");
      resetVideoState();
      statusText.textContent = "Своє зображення завантажено.";
    };
    reader.readAsDataURL(file);
  }

  uploadInput.addEventListener("change", () => handleUploadedFile(uploadInput.files[0]));
  uploadZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    uploadZone.classList.add("dragover");
  });
  uploadZone.addEventListener("dragleave", () => uploadZone.classList.remove("dragover"));
  uploadZone.addEventListener("drop", (event) => {
    event.preventDefault();
    uploadZone.classList.remove("dragover");
    handleUploadedFile(event.dataTransfer.files[0]);
  });

  const previewVideo = document.createElement("video");
  previewVideo.className = "test-preview-video";
  previewVideo.controls = true;
  previewVideo.hidden = true;
  card.appendChild(previewVideo);

  // Дозволяє "продовжити" сцену новим кліпом з того місця, де закінчився
  // попередній (наприклад: хвиля накрила камеру -> новий кадр під водою) -
  // бере останній кадр щойно згенерованого відео просто в браузері
  // (через canvas, без жодного звернення до сервера) і підставляє його
  // як нову вихідну картинку для наступної генерації
  const continueButton = document.createElement("button");
  continueButton.type = "button";
  continueButton.className = "test-continue-button";
  continueButton.textContent = "➜ Взяти останній кадр і продовжити";
  continueButton.hidden = true;
  card.appendChild(continueButton);

  continueButton.addEventListener("click", () => {
    const captureFrame = () => {
      const canvas = document.createElement("canvas");
      canvas.width = previewVideo.videoWidth;
      canvas.height = previewVideo.videoHeight;
      canvas.getContext("2d").drawImage(previewVideo, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL("image/png");

      lastImageData = dataUrl;
      previewImg.src = dataUrl;
      previewImg.hidden = false;
      removeImageButton.hidden = false;
      uploadZone.classList.remove("has-image");
      resetVideoState();
      statusText.textContent = "Останній кадр узято як нову картинку - онови промт (опиши продовження дії) і натисни «Перегенерувати картинку» або одразу «Згенерувати відео».";
    };

    const onSeeked = () => {
      previewVideo.removeEventListener("seeked", onSeeked);
      captureFrame();
    };
    previewVideo.addEventListener("seeked", onSeeked);
    // трохи відступаємо від самого кінця - останній кадр іноді порожній/чорний
    previewVideo.currentTime = Math.max(0, previewVideo.duration - 0.1);
  });

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
      removeImageButton.hidden = false;
      uploadZone.classList.remove("has-image");
      resetVideoState();
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
      const videoUrl = await pollVideoJob(jobId, statusText, previewVideo, continueButton);
      if (videoUrl) {
        // тримаємо байти відео в пам'яті (не лише URL) - потрібно для
        // "Завершити повне відео" (надсилаємо їх на бекенд) і про запас
        // на випадок, якщо сервер засне до того, як натиснуть фіналізацію
        try {
          const videoBlob = await (await fetch(videoUrl)).blob();
          lastVideoData = await blobToDataUrl(videoBlob);
        } catch (err) {
          // не критично - просто не можна буде фіналізувати цю сцену з відео
        }
      }
    } catch (err) {
      statusText.textContent = `Помилка: ${err.message}`;
    } finally {
      videoButton.disabled = false;
    }
  });

  card.getSceneData = () => ({
    voice_text: voiceInput.value,
    subtitle: subtitleInput.value,
    transition: scene.transition,
    image_data: lastVideoData ? null : lastImageData,
    video_data: lastVideoData,
  });

  return card;
}

async function pollVideoJob(jobId, statusText, previewVideo, continueButton) {
  statusText.textContent = "fal.ai генерує відео (може тривати до 3 хв)...";
  const POLL_INTERVAL_MS = 4000;

  while (true) {
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));

    const response = await fetch(`/api/test/video/${jobId}`);
    if (!response.ok) {
      statusText.textContent = "Помилка при перевірці статусу.";
      return null;
    }
    const data = await response.json();

    if (data.status === "done") {
      previewVideo.src = data.video_url;
      previewVideo.hidden = false;
      continueButton.hidden = false;
      statusText.textContent = "Відео готове!";
      return data.video_url;
    }
    if (data.status === "error") {
      statusText.textContent = `Помилка fal.ai: ${data.error}`;
      return null;
    }
  }
}

let currentLanguage = "uk";

async function handleScriptSubmit(event) {
  event.preventDefault();
  clearError(scriptError);
  scenesPanel.hidden = true;
  scenesList.innerHTML = "";
  finalizePanel.hidden = true;
  finalizeVideo.hidden = true;
  clearError(finalizeError);
  finalizeStatus.textContent = "";

  const topic = document.getElementById("topic").value.trim();
  const duration = Number(document.getElementById("duration").value);
  const style = document.getElementById("style").value;
  const language = document.getElementById("language").value;
  currentLanguage = language;

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
    finalizePanel.hidden = false;
  } catch (err) {
    showError(scriptError, err.message);
  } finally {
    scriptSubmit.disabled = false;
    scriptSubmit.textContent = "Згенерувати сценарій";
  }
}

scriptForm.addEventListener("submit", handleScriptSubmit);

async function handleFinalizeClick() {
  clearError(finalizeError);
  finalizeVideo.hidden = true;

  const cards = Array.from(scenesList.children);
  const scenes = cards.map((card) => card.getSceneData());

  const missing = scenes.findIndex((s) => !s.image_data && !s.video_data);
  if (missing !== -1) {
    showError(finalizeError, `Сцена ${missing + 1}: немає ні картинки, ні відео - спочатку згенеруйте хоча б одне.`);
    return;
  }

  finalizeButton.disabled = true;
  finalizeStatus.textContent = "Синтезуємо озвучку й монтуємо відео...";

  try {
    const response = await fetch("/api/test/finalize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenes, language: currentLanguage }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "Не вдалося запустити монтаж");
    }
    const { job_id: jobId } = await response.json();

    const POLL_INTERVAL_MS = 4000;
    while (true) {
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      const statusResponse = await fetch(`/api/test/finalize/${jobId}`);
      if (!statusResponse.ok) {
        throw new Error("Помилка при перевірці статусу монтажу");
      }
      const data = await statusResponse.json();
      if (data.status === "done") {
        finalizeVideo.src = data.video_url;
        finalizeVideo.hidden = false;
        finalizeStatus.textContent = "Готово!";
        break;
      }
      if (data.status === "error") {
        throw new Error(data.error || "Монтаж завершився помилкою");
      }
    }
  } catch (err) {
    showError(finalizeError, err.message);
    finalizeStatus.textContent = "";
  } finally {
    finalizeButton.disabled = false;
  }
}

finalizeButton.addEventListener("click", handleFinalizeClick);
