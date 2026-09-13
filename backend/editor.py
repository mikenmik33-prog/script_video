"""
Модуль монтажу відео через FFmpeg.

Збирає з окремих сцен (зображення + динамічні субтитри "слово за
словом" від subtitles.py + озвучка) одне вертикальне відео 720x1280,
додає фонову музику і експортує готовий MP4.

Кожен крок - окрема невелика функція навколо одного виклику FFmpeg,
щоб конвеєр було легко читати і змінювати.
"""

import os
import subprocess

from backend import subtitles as subtitles_module

WIDTH, HEIGHT = 720, 1280  # 720p - дешевше і швидше кодувати (CPU) та дешевше для платних відео-API
FPS = 24  # 24 замість 30 - помітно менше кадрів для кодування (легше для CPU)
MUSIC_VOLUME = 0.18

# Переходи між сценами - справжній xfade (кадри двох сцен перетікають
# один в інший), а не старе "згасання в чорне і назад", яке давало
# чорний спалах між кожною парою сцен
XFADE_TRANSITIONS = {
    "fade": "fade",
    "slide": "slideleft",
    "cut": "fade",  # "різкий" перехід реалізуємо як дуже короткий fade -
                    # візуально як різкий різ, але без гілкування ffmpeg-графа
}
DEFAULT_TRANSITION_SECONDS = 0.45
CUT_TRANSITION_SECONDS = 0.08


def _run_ffmpeg(args: list):
    result = subprocess.run(["ffmpeg", "-y", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg помилка (монтаж): {result.stderr.decode(errors='ignore')}")


def _probe_media_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFprobe помилка: {result.stderr.decode(errors='ignore')}")
    return float(result.stdout.decode().strip())


def _escape_drawtext(text: str) -> str:
    """Екранує спецсимволи ffmpeg drawtext (\\, :, ', %) у тексті слова."""
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\\'")
    text = text.replace("%", "\\%")
    return text


def _create_scene_clip(frames: list, output_path: str, work_dir: str, clip_name: str):
    """Перетворює послідовність кадрів сцени (зображення + тривалість показу
    кожного - для динамічного виділення слів у субтитрах) на один
    відеокліп через FFmpeg concat demuxer (один виклик FFmpeg, навіть
    якщо кадрів багато - важливо для слабких CPU безкоштовних хостингів).

    Кліп навмисно БЕЗ переходів усередині - перехід між сценами тепер
    робиться окремо, через xfade у _build_transition_chain(), інакше
    старе рішення "згасання в чорне на початку/кінці кожного кліпу"
    давало помітний чорний спалах між сусідніми сценами."""
    list_path = os.path.join(work_dir, f"{clip_name}_frames.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for frame_path, frame_duration in frames:
            absolute = os.path.abspath(frame_path).replace("'", "'\\''")
            f.write(f"file '{absolute}'\n")
            f.write(f"duration {frame_duration}\n")
        # concat demuxer вимагає повторити останній файл без duration,
        # інакше тривалість останнього кадру ігнорується
        last_absolute = os.path.abspath(frames[-1][0]).replace("'", "'\\''")
        f.write(f"file '{last_absolute}'\n")

    filters = [
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease",
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2",
    ]

    _run_ffmpeg([
        "-f", "concat",
        "-safe", "0",
        "-i", list_path,
        "-vf", ",".join(filters),
        "-r", str(FPS),
        "-pix_fmt", "yuv420p",
        # ultrafast - кодування набагато дешевше для CPU (важливо на
        # безкоштовних хостингах з дуже обмеженим CPU, напр. Render Free)
        "-preset", "ultrafast",
        output_path,
    ])


def _create_scene_clip_from_video(video_path: str, subtitle_text: str, duration: float, work_dir: str, clip_name: str) -> str:
    """Як _create_scene_clip, але з готового AI-відеокліпу сцени (fal.ai)
    замість послідовності кадрів картинки.

    Відео підганяється під РЕАЛЬНУ тривалість озвучки сцени - обрізається,
    якщо довше, або "заморожує" останній кадр (tpad), якщо коротше (кліпи
    fal.ai мають фіксовану тривалість 6с/10с, що рідко збігається з
    тривалістю озвучки). Субтитри накладаються прямо на рухоме відео
    через ffmpeg drawtext - для картинок субтитри "впечені" в кадри через
    PIL (subtitles.generate_word_highlight_frames), а тут та сама
    розкладка рядків/тривалостей (subtitles.compute_word_overlay_specs)
    використовується для позиціонування drawtext-фільтрів замість
    малювання."""
    source_duration = _probe_media_duration(video_path)

    if source_duration > duration + 0.02:
        fitted_path = os.path.join(work_dir, f"{clip_name}_fitted.mp4")
        _run_ffmpeg([
            "-i", video_path,
            "-t", f"{duration:.3f}",
            "-an",
            "-preset", "ultrafast",
            fitted_path,
        ])
    elif source_duration < duration - 0.02:
        fitted_path = os.path.join(work_dir, f"{clip_name}_fitted.mp4")
        deficit = duration - source_duration
        _run_ffmpeg([
            "-i", video_path,
            "-vf", f"tpad=stop_mode=clone:stop_duration={deficit:.3f}",
            "-an",
            "-preset", "ultrafast",
            fitted_path,
        ])
    else:
        fitted_path = video_path

    specs = subtitles_module.compute_word_overlay_specs(subtitle_text, duration, WIDTH, HEIGHT)

    filters = [
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease",
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2",
    ]

    font_path = subtitles_module.FONT_PATH
    font_size = subtitles_module.SUBTITLE_FONT_SIZE
    outline_width = subtitles_module.SUBTITLE_OUTLINE_WIDTH
    highlight_r, highlight_g, highlight_b = subtitles_module.SUBTITLE_HIGHLIGHT_COLOR
    highlight_hex = f"0x{highlight_r:02X}{highlight_g:02X}{highlight_b:02X}"

    for spec in specs:
        word = _escape_drawtext(spec["word"])
        common = (
            f"fontfile={font_path}:text='{word}':x={spec['x']:.1f}:y={spec['y']:.1f}"
            f":fontsize={font_size}:bordercolor=black:borderw={outline_width}"
        )
        # білий варіант слова видно ВЕСЬ час сцени, а жовтий - лише в
        # момент, коли слово "звучить" - малюється поверх у ту саму
        # позицію, тому виглядає як зміна кольору активного слова
        filters.append(f"drawtext={common}:fontcolor=white")
        filters.append(f"drawtext={common}:fontcolor={highlight_hex}:enable='between(t\\,{spec['start']:.3f}\\,{spec['end']:.3f})'")

    output_path = os.path.join(work_dir, f"{clip_name}.mp4")
    _run_ffmpeg([
        "-i", fitted_path,
        "-vf", ",".join(filters),
        "-r", str(FPS),
        "-pix_fmt", "yuv420p",
        "-preset", "ultrafast",
        output_path,
    ])
    return output_path


def _build_transition_chain(clip_paths: list, clip_durations: list, transitions: list, output_path: str):
    """Склеює кліпи сцен в один відеоряд із плавними переходами (xfade) -
    кадри двох сусідніх сцен буквально перетікають один в інший
    (crossfade чи slide), замість різкого монтажного склеювання.

    transitions[i] - тип переходу МІЖ сценою i та сценою i+1 (тип
    останньої сцени не використовується - переходити вже нікуди).

    Повертає РЕАЛЬНУ тривалість отриманого відео - кожен xfade-перехід
    "з'їдає" частину тривалості (сцени накладаються одна на одну), тому
    підсумкове відео коротше за просту суму scene["duration"]. Виклик
    має компенсувати цю різницю (див. build_video), інакше в кінці
    зникне кілька секунд озвучки/музики."""
    if len(clip_paths) == 1:
        # нема з чим переходити - просто перекодовуємо єдиний кліп
        _run_ffmpeg([
            "-i", clip_paths[0],
            "-r", str(FPS), "-pix_fmt", "yuv420p", "-preset", "ultrafast",
            output_path,
        ])
        return clip_durations[0]

    args = []
    for path in clip_paths:
        args += ["-i", path]

    filter_parts = []
    prev_label = "0:v"
    running_duration = clip_durations[0]

    for i in range(1, len(clip_paths)):
        transition_key = transitions[i - 1] if i - 1 < len(transitions) else "fade"
        xfade_name = XFADE_TRANSITIONS.get(transition_key, "fade")
        base_duration = CUT_TRANSITION_SECONDS if transition_key == "cut" else DEFAULT_TRANSITION_SECONDS
        # перехід не може бути довшим за жоден із двох кліпів, що зʼєднуються
        duration = max(min(base_duration, clip_durations[i - 1] * 0.4, clip_durations[i] * 0.4), 0.05)

        offset = max(running_duration - duration, 0)
        label = f"v{i}"
        filter_parts.append(
            f"[{prev_label}][{i}:v]xfade=transition={xfade_name}:duration={duration:.3f}:offset={offset:.3f}[{label}]"
        )
        running_duration = running_duration + clip_durations[i] - duration
        prev_label = label

    args += [
        "-filter_complex", ";".join(filter_parts),
        "-map", f"[{prev_label}]",
        "-r", str(FPS),
        "-pix_fmt", "yuv420p",
        "-preset", "ultrafast",
        output_path,
    ]
    _run_ffmpeg(args)
    return running_duration


def _pad_video_duration(video_path: str, deficit_seconds: float, work_dir: str) -> str:
    """Додає deficit_seconds в кінець відео, "заморожуючи" останній кадр -
    компенсує тривалість, яку "з'їли" xfade-переходи, щоб відео не
    виявилось коротшим за озвучку/музику (інакше кінець аудіо обрізало б).
    (tpad-у stop_duration - це саме тривалість ДОПОВНЕННЯ, а не цільова
    підсумкова тривалість)."""
    padded_path = os.path.join(work_dir, "video_only_padded.mp4")
    _run_ffmpeg([
        "-i", video_path,
        "-vf", f"tpad=stop_mode=clone:stop_duration={deficit_seconds:.3f}",
        "-r", str(FPS),
        "-pix_fmt", "yuv420p",
        "-preset", "ultrafast",
        padded_path,
    ])
    return padded_path


def _concat_media(file_paths: list, list_file_path: str, output_path: str, extra_args=None):
    """Склеює список файлів (відео або аудіо) через concat demuxer FFmpeg."""
    with open(list_file_path, "w", encoding="utf-8") as f:
        for path in file_paths:
            absolute = os.path.abspath(path).replace("'", "'\\''")
            f.write(f"file '{absolute}'\n")

    args = ["-f", "concat", "-safe", "0", "-i", list_file_path]
    args += extra_args if extra_args is not None else ["-c", "copy"]
    args += [output_path]
    _run_ffmpeg(args)


def _pick_music_file(music_dir: str):
    if not os.path.isdir(music_dir):
        return None
    for name in sorted(os.listdir(music_dir)):
        if name.lower().endswith((".mp3", ".wav", ".m4a", ".aac")):
            return os.path.join(music_dir, name)
    return None


def _build_music_track(duration: float, music_dir: str, work_dir: str) -> str:
    """Готує доріжку фонової музики: реальний трек з assets/music, якщо він
    є, або тиху тестову доріжку - якщо ні."""
    music_path = _pick_music_file(music_dir)
    output_path = os.path.join(work_dir, "music.wav")

    if music_path:
        _run_ffmpeg([
            "-stream_loop", "-1",
            "-i", music_path,
            "-t", str(duration),
            "-af", f"volume={MUSIC_VOLUME}",
            output_path,
        ])
    else:
        _run_ffmpeg([
            "-f", "lavfi",
            "-i", f"sine=frequency=220:duration={duration}",
            "-af", f"volume={MUSIC_VOLUME}",
            output_path,
        ])
    return output_path


def _mix_audio(voice_path: str, music_path: str, output_path: str):
    _run_ffmpeg([
        "-i", voice_path,
        "-i", music_path,
        "-filter_complex",
        "[0:a]volume=1.0[a0];[1:a]volume=1.0[a1];[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[aout]",
        "-map", "[aout]",
        output_path,
    ])


def build_video(scenes: list, scene_images: list, voice_files: list, work_dir: str, music_dir: str, output_path: str, progress_callback=None, scene_videos: list = None) -> str:
    """
    Головна функція монтажу.

    scenes            - сцени сценарію (тривалість, субтитр, тип переходу)
    scene_images      - шляхи до згенерованих зображень сцен (той самий порядок)
    voice_files       - шляхи до аудіофайлів озвучки сцен (той самий порядок)
    work_dir          - тимчасова робоча директорія для проміжних файлів
    music_dir         - директорія з фоновою музикою (assets/music)
    output_path       - шлях до фінального MP4
    progress_callback - необов'язкова функція(fraction: float 0..1), яку
        викликаємо після кожного важкого кроку. Кодування відео - це
        найдовший етап конвеєра (особливо на слабких CPU безкоштовних
        хостингів), тому без цього прогрес-бар виглядав би "завислим"
        на весь час монтажу.
    scene_videos      - необов'язковий список (той самий порядок, що й
        scenes) шляхів до готових AI-відеокліпів (fal.ai) для окремих
        сцен, або None на позиції сцени без відео - тоді для неї, як і
        раніше, використовується scene_images. Дозволяє змішувати в
        одному відео і статичні картинки, і "оживлені" AI-сцени.

    Повертає шлях до готового файлу (== output_path).
    """
    os.makedirs(work_dir, exist_ok=True)
    if scene_videos is None:
        scene_videos = [None] * len(scenes)

    # +5 - склеювання відео, склеювання голосу, музика, мікс аудіо, фінальний mux
    total_steps = len(scenes) + 5
    completed_steps = 0

    def _report_progress():
        nonlocal completed_steps
        completed_steps += 1
        if progress_callback is not None:
            progress_callback(completed_steps / total_steps)

    clip_paths = []
    clip_durations = []
    transitions = []
    for scene, image_path, video_path in zip(scenes, scene_images, scene_videos):
        clip_name = f"scene_{scene['scene']:02d}"

        if video_path:
            clip_path = _create_scene_clip_from_video(
                video_path, scene["subtitle"], scene["duration"], work_dir, clip_name,
            )
        else:
            frames = subtitles_module.generate_word_highlight_frames(
                image_path, scene["subtitle"], scene["duration"], work_dir, clip_name,
            )
            clip_path = os.path.join(work_dir, f"{clip_name}.mp4")
            _create_scene_clip(frames, clip_path, work_dir, clip_name)

        clip_paths.append(clip_path)
        # generate_word_highlight_frames і _create_scene_clip_from_video
        # обидва гарантують, що кліп триває саме scene["duration"]
        clip_durations.append(scene["duration"])
        transitions.append(scene["transition"])
        _report_progress()

    video_only_path = os.path.join(work_dir, "video_only.mp4")
    video_duration = _build_transition_chain(clip_paths, clip_durations, transitions, video_only_path)

    # xfade-переходи "з'їдають" частину тривалості (сцени накладаються
    # одна на одну) - доповнюємо відео до початкової сумарної тривалості,
    # інакше при фінальному mux-і обріже кінець озвучки/музики
    total_scenes_duration = sum(clip_durations)
    deficit = total_scenes_duration - video_duration
    if deficit > 0.02:
        video_only_path = _pad_video_duration(video_only_path, deficit, work_dir)
    _report_progress()

    voice_track_path = os.path.join(work_dir, "voice_track.wav")
    _concat_media(
        voice_files,
        os.path.join(work_dir, "voices.txt"),
        voice_track_path,
        extra_args=["-ar", "44100", "-ac", "2"],
    )
    _report_progress()

    music_track_path = _build_music_track(total_scenes_duration, music_dir, work_dir)
    _report_progress()

    mixed_audio_path = os.path.join(work_dir, "mixed_audio.wav")
    _mix_audio(voice_track_path, music_track_path, mixed_audio_path)
    _report_progress()

    _run_ffmpeg([
        "-i", video_only_path,
        "-i", mixed_audio_path,
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ])
    _report_progress()

    return output_path
