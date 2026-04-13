import sys
import argparse
import textwrap
import os
import urllib.request
import subprocess
import shutil
import json
import math
import time

# ============================================================
# PENTING: Deteksi FFmpeg HARUS dilakukan SEBELUM import MoviePy
# karena imageio_ffmpeg meng-cache path FFmpeg saat pertama kali di-import.
# ============================================================
def detect_ffmpeg_config():
    """Auto-detect FFmpeg terbaik: prioritaskan system ffmpeg dengan NVENC.
    
    Returns dict: { 'ffmpeg_path', 'codec', 'preset', 'ffmpeg_params', 'label' }
    MoviePy sudah menambahkan -preset sendiri, jadi kita pakai field 'preset' terpisah.
    """
    system_ffmpeg = shutil.which('ffmpeg')
    
    if system_ffmpeg:
        try:
            result = subprocess.run(
                [system_ffmpeg, '-encoders'],
                capture_output=True, text=True, timeout=5
            )
            if 'h264_nvenc' in result.stdout:
                # Set env SEBELUM moviepy di-import
                os.environ['IMAGEIO_FFMPEG_EXE'] = system_ffmpeg
                return {
                    'ffmpeg_path': system_ffmpeg,
                    'codec': 'h264_nvenc',
                    'preset': 'fast',
                    'ffmpeg_params': [],
                    'label': f'GPU NVENC ({system_ffmpeg})'
                }
        except Exception:
            pass
    
    # Fallback: libx264 CPU encoding
    return {
        'ffmpeg_path': None,
        'codec': 'libx264',
        'preset': 'ultrafast',
        'ffmpeg_params': [],
        'label': 'CPU libx264 (ultrafast)'
    }

# Detect encoder dan set IMAGEIO_FFMPEG_EXE SEBELUM import moviepy
FFMPEG_CONFIG = detect_ffmpeg_config()
print(f"Encoder: {FFMPEG_CONFIG['label']}", file=sys.stderr)

# Sekarang baru aman import MoviePy (akan pakai FFmpeg yang sudah kita set)
from moviepy import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_audioclips, ColorClip
from moviepy.video.fx import CrossFadeIn, CrossFadeOut
from arabic_reshaper import reshape
from bidi.algorithm import get_display
import numpy as np

# Mencari folder tempat script ini berada secara otomatis
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def ensure_local_file(path_or_url, folder=""):
    """Mendownload file ke folder spesifik jika input adalah URL, atau mencari file di folder tersebut."""

    if path_or_url.startswith("http"):
        # Gunakan nama file dari URL
        filename = path_or_url.split("/")[-1]
        save_path = os.path.join(folder, filename) if folder else filename

        if not os.path.exists(save_path):
            print(f"Downloading: {path_or_url} to {save_path}...", file=sys.stderr)
            req = urllib.request.Request(
                path_or_url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
            )
            with urllib.request.urlopen(req) as response, open(save_path, 'wb') as out_file:
                out_file.write(response.read())
        return save_path

    # Jika bukan URL, cek apakah file ada di root atau di folder yang ditentukan
    if folder:
        # 1. Cek di root
        if os.path.exists(path_or_url):
            return path_or_url
        # 2. Cek di dalam folder
        path_in_folder = os.path.join(folder, path_or_url)
        if os.path.exists(path_in_folder):
            return path_in_folder

    return path_or_url

def _make_text_clip(text, font_size, color, font, max_w, **kwargs):
    """Helper: Membuat satu TextClip dengan ukuran font tertentu."""
    return TextClip(
        text=text,
        font_size=font_size,
        color=color,
        font=font,
        method='caption',
        size=(max_w, None),
        **kwargs
    )

def create_scaled_text(text, font, initial_size, color, max_w, max_h, **kwargs):
    """Membuat TextClip yang otomatis mengecil jika teks terlalu panjang/tinggi.

    Menggunakan binary search untuk menemukan font_size terbesar yang muat.
    Jauh lebih cepat dari linear search: O(log n) vs O(n) pembuatan TextClip.
    Contoh: range 80→15 = max ~5 iterasi (bukan ~17).
    """
    min_size = 15

    # Quick check: jika ukuran terbesar sudah muat, langsung return
    clip = _make_text_clip(text, initial_size, color, font, max_w, **kwargs)
    if clip.h <= max_h:
        return clip

    # Quick check: jika ukuran terkecil pun tidak muat, langsung return
    smallest_clip = _make_text_clip(text, min_size, color, font, max_w, **kwargs)
    if smallest_clip.h > max_h:
        return smallest_clip

    # Binary search: cari font_size terbesar yang masih muat
    low = min_size
    high = initial_size
    best_clip = smallest_clip

    while low <= high:
        mid = (low + high) // 2
        clip = _make_text_clip(text, mid, color, font, max_w, **kwargs)

        if clip.h <= max_h:
            best_clip = clip
            low = mid + 1   # Coba ukuran lebih besar
        else:
            high = mid - 1  # Terlalu besar, kurangi

    return best_clip

def split_text_to_pages(text, n_pages):
    """Membagi teks menjadi beberapa halaman secara proporsional."""
    if n_pages <= 1:
        return [text]
    words = text.split()
    total_words = len(words)
    if total_words == 0:
        return [""] * n_pages
    words_per_page = math.ceil(total_words / n_pages)
    pages = []
    for i in range(n_pages):
        start = i * words_per_page
        end = (i + 1) * words_per_page
        pages.append(" ".join(words[start:end]))
    return pages

def create_quran_video(ayat_texts, translations, audio_paths, bg_path, output_name, watermark, hook, overlay_opacity):
    start_time = time.time()

    # Definisikan path absolut untuk folder-folder dasar
    audio_dir = os.path.join(BASE_DIR, "audio")
    video_bg_dir = os.path.join(BASE_DIR, "video_bg")
    output_dir = os.path.join(BASE_DIR, "output")

    # Pastikan folder dasar ada di dalam direktori script
    for folder in [audio_dir, video_bg_dir, output_dir]:
        if not os.path.exists(folder):
            os.makedirs(folder)

    # Split input by separator '|'
    list_ayats = ayat_texts.split('|')
    list_translations = translations.split('|')
    list_audios = audio_paths.split('|')

    # 1. Load & Concatenate Audios (Handle URLs & Folders)
    audio_clips = []
    for a in list_audios:
        local_path = ensure_local_file(a, folder=audio_dir)
        audio_clips.append(AudioFileClip(local_path))

    final_audio = concatenate_audioclips(audio_clips)
    total_duration = final_audio.duration

    # 2. Load Background & Adjust duration (Handle URL & Folders)
    local_bg = ensure_local_file(bg_path, folder=video_bg_dir)
    video = VideoFileClip(local_bg)
    if video.duration < total_duration:
        # Video lebih pendek dari audio -> Slow down (agar tidak terpotong)
        speed_factor = video.duration / total_duration
        video = video.with_speed_scaled(speed_factor)
    else:
        # Video lebih panjang atau sama -> Jangan dipercepat (agar tetap normal), potong jika perlu
        video = video.with_duration(total_duration)

    video = video.with_audio(final_audio)

    # 2b. Pre-bake overlay hitam langsung ke background (lebih cepat daripada layer terpisah)
    # Ini mengurangi jumlah layer compositing = lebih cepat per frame
    opacity = float(overlay_opacity)
    video = video.image_transform(lambda frame: (frame * (1 - opacity)).astype(np.uint8))

    # 3. Watermark (Visible all time)
    txt_watermark = TextClip(text=watermark, font_size=12, color='white', font=os.path.join(BASE_DIR, 'Arial.ttf'),
                             method='label').with_opacity(0.5)
    txt_watermark = txt_watermark.with_position((80, video.h - txt_watermark.h - 200)).with_duration(total_duration)

    # 4. Hook Text (Visible all time) - Style: Professional Plate
    # Hook dibatasi tingginya maksimal 15% dari tinggi video
    txt_hook = create_scaled_text(
        text=hook.upper(),
        font=os.path.join(BASE_DIR, 'Lora.ttf'),
        initial_size=42,
        color='white',
        max_w=int(video.w * 0.8),
        max_h=int(video.h * 0.15),
        text_align='center',
        margin=(40, 15),
        bg_color=(0, 0, 0, 140)
    )

    # Posisikan Hook dengan sedikit efek muncul (Fade)
    txt_hook = txt_hook.with_position(('center', int(video.h * 0.12))).with_duration(total_duration)
    txt_hook = txt_hook.with_effects([CrossFadeIn(duration=1.0)])

    # 5. Create Verse Clips Sequentially
    all_text_clips = []
    current_start = 0

    for ayat, trans, a_clip in zip(list_ayats, list_translations, audio_clips):
        duration = a_clip.duration

        # --- AUTOMATIC PAGING ---
        # Jika teks terlalu panjang, bagi menjadi beberapa "halaman" agar tetap terbaca profesional
        chars_per_page_arabic = 200
        chars_per_page_trans = 250

        num_pages = math.ceil(max(len(ayat) / chars_per_page_arabic, len(trans) / chars_per_page_trans))
        pages_a = split_text_to_pages(ayat, num_pages)
        pages_t = split_text_to_pages(trans, num_pages)
        page_duration = duration / num_pages

        for p_idx in range(num_pages):
            p_ayat = pages_a[p_idx]
            p_trans = pages_t[p_idx]
            p_start = current_start + (p_idx * page_duration)

            # --- ARABIC RENDERING ---
            arabic_width = max(20, int(35 * (video.w / 1080)))
            wrapped_ayat = textwrap.fill(p_ayat, width=arabic_width)

            tx_a = create_scaled_text(
                text=wrapped_ayat,
                font=os.path.join(BASE_DIR, 'UthmanicHafs.otf'),
                initial_size=80,
                color='#FFD700',
                max_w=int(video.w * 0.9),
                max_h=int(video.h * 0.40),
                stroke_color='#FFD700',
                stroke_width=1,
                text_align='center',
                margin=(20, 20),
                interline=20
            )

            # --- TRANSLATION RENDERING ---
            chars_per_line = max(25, int(45 * (video.w / 1080)))
            wrapped_trans = textwrap.fill(p_trans, width=chars_per_line)

            tx_t = create_scaled_text(
                text=wrapped_trans,
                font=os.path.join(BASE_DIR, 'OpenSauceOne-Bold.ttf'),
                initial_size=35,
                color='white',
                max_w=int(video.w * 0.9),
                max_h=int(video.h * 0.30),
                stroke_color='white',
                stroke_width=0,
                text_align='center',
                margin=(20, 20),
                interline=10
            )

            # Center vertically as a group
            gap = 40
            v_height = tx_a.h + gap + tx_t.h
            v_start_y = (video.h - v_height) // 2

            tx_a = tx_a.with_position(('center', v_start_y)).with_start(p_start).with_duration(page_duration)
            tx_t = tx_t.with_position(('center', v_start_y + tx_a.h + gap)).with_start(p_start).with_duration(page_duration)

            # Transitions - Khusus halaman pertama FadeIn, halaman terakhir FadeOut
            # Atau gunakan CrossFade halus untuk setiap perpindahan halaman
            tx_a = tx_a.with_effects([CrossFadeIn(duration=0.4), CrossFadeOut(duration=0.4)])
            tx_t = tx_t.with_effects([CrossFadeIn(duration=0.4), CrossFadeOut(duration=0.4)])

            all_text_clips.extend([tx_a, tx_t])

        current_start += duration

    # 6. Combine All
    # Overlay sudah di-bake ke background, jadi lebih sedikit layer = lebih cepat
    final_video = CompositeVideoClip([video, txt_watermark, txt_hook] + all_text_clips)

    # Simpan di folder output jika path tidak mengandung folder
    if not os.path.dirname(output_name):
        output_name = os.path.join(output_dir, output_name)

    print(f"Rendering final video to: {output_name}...", file=sys.stderr)
    final_video.write_videofile(
        output_name,
        fps=24,
        codec=FFMPEG_CONFIG['codec'],
        preset=FFMPEG_CONFIG['preset'],
        ffmpeg_params=FFMPEG_CONFIG['ffmpeg_params'] or None,
        threads=4,
        logger=None
    )

    # Berikan output JSON untuk n8n agar mudah di-parse
    elapsed = time.time() - start_time
    minutes, seconds = divmod(elapsed, 60)
    result = {
        "status": "success",
        "output_file": output_name,
        "absolute_path": os.path.abspath(output_name),
        "duration": float(total_duration),
        "process_time": round(elapsed, 2),
        "process_time_formatted": f"{int(minutes)}m {seconds:.1f}s",
        "encoder": FFMPEG_CONFIG['label']
    }
    print(json.dumps(result))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quran Video Generator for Shorts/Reels - Professional & Dynamic")

    # Kelompokkan Argumen agar lebih rapi
    content = parser.add_argument_group('Konten Video')
    content.add_argument("--ayat", required=True, help="Teks ayat Arab (Gunakan | untuk memisahkan multi-ayat)")
    content.add_argument("--trans", required=True, help="Teks terjemahan (Gunakan | untuk memisahkan)")
    content.add_argument("--audio", required=True, help="Path lokal atau URL MP3 (Gunakan | untuk memisahkan)")

    assets = parser.add_argument_group('Aset & Styling')
    assets.add_argument("--bg", required=True, help="Path file video background (.mp4)")
    assets.add_argument("--hook", default="", help="Teks Hook/Judul di bagian atas")
    assets.add_argument("--watermark", default="", help="Teks watermark di kiri bawah")
    assets.add_argument("--overlay", default=0.3, type=float, help="Opacity overlay hitam (0.0 - 1.0, default: 0.3)")

    output = parser.add_argument_group('Output')
    output.add_argument("--output", default="output_video.mp4", help="Nama file hasil render")

    args = parser.parse_args()

    # Jalankan Generator
    create_quran_video(
        ayat_texts=args.ayat,
        translations=args.trans,
        audio_paths=args.audio,
        bg_path=args.bg,
        output_name=args.output,
        watermark=args.watermark,
        hook=args.hook,
        overlay_opacity=args.overlay
    )
