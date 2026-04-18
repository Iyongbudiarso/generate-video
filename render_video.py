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
from moviepy import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_audioclips, ColorClip, VideoClip, CompositeAudioClip
from moviepy.video.fx import CrossFadeIn, CrossFadeOut
from arabic_reshaper import reshape
from bidi.algorithm import get_display
import numpy as np

# Mencari folder tempat script ini berada secara otomatis
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def create_audio_visualizer(audio_clip, width, height, fps=24, num_bars=11, color=(255,215,0)):
    """Membuat klip visualizer gelombang suara (bar putus-putus) berdasarkan amplitudo audio."""
    sr = 22050
    try:
        audio_data = audio_clip.to_soundarray(fps=sr)
        if audio_data.ndim == 2:
            audio_data = audio_data.mean(axis=1) # konversi ke mono
    except Exception:
        # Fallback aman jika gagal membaca audio array
        audio_data = np.zeros(int(audio_clip.duration * sr))

    samples_per_frame = int(sr / fps)
    num_frames = int(audio_clip.duration * fps) + 2

    # Hitung energi per frame
    frame_energies = []
    for i in range(num_frames):
        start = i * samples_per_frame
        end = start + samples_per_frame
        chunk = audio_data[start:end]
        if len(chunk) > 0:
            rms = np.sqrt(np.mean(chunk**2))
        else:
            rms = 0
        frame_energies.append(rms)

    max_energy = max(frame_energies) if len(frame_energies) > 0 and max(frame_energies) > 0 else 1.0
    # Normalisasi dan beri boost
    frame_energies = [min(1.0, (e / max_energy) * 2.0) for e in frame_energies]

    bar_width = width // num_bars
    gap = int(bar_width * 0.2) if int(bar_width * 0.2) > 0 else 1
    actual_bar_w = bar_width - gap

    def get_bars_frame(t, return_mask=False):
        frame_idx = int(t * fps)
        if frame_idx >= len(frame_energies):
            frame_idx = len(frame_energies) - 1
        energy = frame_energies[frame_idx]

        # Jika mask, return float32 array. Jika tidak, uint8.
        dtype = np.float32 if return_mask else np.uint8
        shape = (height, width) if return_mask else (height, width, 3)
        frame = np.zeros(shape, dtype=dtype)

        for i in range(num_bars):
            # Efek lengkungan (tengah lebih tinggi)
            center_dist = abs(i - (num_bars // 2)) / max(1, (num_bars // 2))
            band_factor = 1.0 - (center_dist * 0.4)
            # Variasi sinusoidal kecil agar tidak terlalu kaku
            variation = np.sin((t * 15) + i * 2) * 0.3 + 0.7

            bar_h = int(height * energy * band_factor * variation)
            bar_h = max(2, min(height, bar_h)) # Pastikan selalu ada titik walau sunyi

            x1 = i * bar_width + gap // 2
            x2 = x1 + actual_bar_w
            y1 = height - bar_h
            y2 = height

            if return_mask:
                frame[y1:y2, x1:x2] = 1.0
            else:
                frame[y1:y2, x1:x2] = color

        return frame

    clip = VideoClip(lambda t: get_bars_frame(t, return_mask=False), duration=audio_clip.duration)
    mask = VideoClip(lambda t: get_bars_frame(t, return_mask=True), duration=audio_clip.duration)
    return clip.with_mask(mask)


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
        # 1. Cek absolute path atau relative ke CWD
        if os.path.exists(path_or_url):
            return path_or_url
        # 2. Cek di BASE_DIR (folder tempat script berada)
        path_in_base = os.path.join(BASE_DIR, path_or_url)
        if os.path.exists(path_in_base):
            return path_in_base
        # 3. Cek di dalam folder spesifik (misal /audio, /video_bg)
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

def apply_rounded_corners(clip, radius=20):
    """Membuat mask rounded rectangle dan menerapkannya ke clip."""
    w, h = clip.size
    r = min(radius, w // 2, h // 2)

    # Buat mask array (1 = visible, 0 = transparent)
    mask = np.ones((h, w), dtype=np.float32)

    # Buat grid koordinat untuk setiap corner
    y, x = np.ogrid[:h, :w]

    # Top-left corner
    corner_mask = (x - r) ** 2 + (y - r) ** 2 > r ** 2
    mask[:r, :r][corner_mask[:r, :r]] = 0

    # Top-right corner
    corner_mask = (x - (w - r - 1)) ** 2 + (y - r) ** 2 > r ** 2
    mask[:r, w-r:][corner_mask[:r, w-r:]] = 0

    # Bottom-left corner
    corner_mask = (x - r) ** 2 + (y - (h - r - 1)) ** 2 > r ** 2
    mask[h-r:, :r][corner_mask[h-r:, :r]] = 0

    # Bottom-right corner
    corner_mask = (x - (w - r - 1)) ** 2 + (y - (h - r - 1)) ** 2 > r ** 2
    mask[h-r:, w-r:][corner_mask[h-r:, w-r:]] = 0

    from moviepy import ImageClip
    mask_clip = ImageClip(mask, is_mask=True).with_duration(clip.duration)
    return clip.with_mask(mask_clip)

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

def create_quran_video(ayat_texts, translations, audio_paths, bg_path, output_name, watermark, hook, overlay_opacity, taawudz_url=None, surah="", cta="", latin_texts="", audio_bg_url="", gap_duration=0.0, pitch_factor=1.0):
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
    list_latins = latin_texts.split('|') if latin_texts else [""] * len(list_ayats)


    # 1. Load, Pitch Shift & Concatenate Audios 
    # 1a. Audio ayat-ayat (Terapkan Pitch Shift untuk ngecoh algoritma Content ID)
    audio_clips = []
    for a in list_audios:
        local_path = ensure_local_file(a, folder=audio_dir)
        a_clip = AudioFileClip(local_path)
        if pitch_factor != 1.0:
            a_clip = a_clip.with_speed_scaled(pitch_factor)
        audio_clips.append(a_clip)

    # 1b. Ta'awudz (Audzubillah)
    taawudz_duration = 0
    taawudz_clip = None
    if taawudz_url and taawudz_url.lower() != 'none':
        local_taawudz = ensure_local_file(taawudz_url, folder=audio_dir)
        taawudz_clip = AudioFileClip(local_taawudz)
        if pitch_factor != 1.0:
            taawudz_clip = taawudz_clip.with_speed_scaled(pitch_factor)
        taawudz_duration = taawudz_clip.duration
        print(f"Ta'awudz audio loaded: {taawudz_duration:.1f}s", file=sys.stderr)

    # 1c. Gabungkan dengan strategi "Jeda/Gap" menggunakan CompositeAudioClip
    current_time = 0.0
    voice_clips = []
    
    if taawudz_clip:
        voice_clips.append(taawudz_clip.with_start(current_time))
        current_time += taawudz_duration + gap_duration

    for a_clip in audio_clips:
        voice_clips.append(a_clip.with_start(current_time))
        current_time += a_clip.duration + gap_duration
        
    voice_audio = CompositeAudioClip(voice_clips)
    
    # Total durasi dikurangi gap paling akhir yang tidak ada visualnya
    total_duration = current_time if gap_duration == 0 else current_time - gap_duration

    # 1d. Tambahkan Audio Background (Musik/Ambient) Jika Ada
    final_audio = voice_audio
    if audio_bg_url and audio_bg_url.lower() != 'none':
        local_audio_bg = ensure_local_file(audio_bg_url, folder=audio_dir)
        bg_audio_clip = AudioFileClip(local_audio_bg)

        # Mengecilkan suara background agar tidak menimpa suara lantunan (sekitar 15%)
        # Kompatibel dengan MoviePy v2
        bg_audio_clip = bg_audio_clip.with_volume_scaled(0.15)

        # Looping jika audio_bg lebih pendek, atau potong jika lebih panjang
        if bg_audio_clip.duration < total_duration:
            num_loops = math.ceil(total_duration / bg_audio_clip.duration)
            bg_audio_clip = concatenate_audioclips([bg_audio_clip] * num_loops)

        bg_audio_clip = bg_audio_clip.with_duration(total_duration)

        # Gabungkan suara lantunan (voice) dengan suara background
        final_audio = CompositeAudioClip([bg_audio_clip, voice_audio])

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
    txt_watermark = txt_watermark.with_position((80, video.h - txt_watermark.h - 200)).with_duration(total_duration)    # 4. Kalkulasi Layout Area Dinamis
    # Memastikan teks (Arab/Latin/Terjemah) tidak menabrak Hook di atas & CTA di bawah.
    safe_top = int(video.h * 0.10) # 10% dari atas
    safe_bottom = video.h - 150 # reserve area bawah

    # Hook Text
    hook_max_w = int(video.w * 0.8)
    txt_hook_params = {
        'text': hook.upper(), 'font': os.path.join(BASE_DIR, 'Montserrat-Bold.ttf'),
        'font_size': 42, 'color': 'black', 'stroke_color': 'black', 'stroke_width': 1,
        'bg_color': 'white', 'margin': (30, 25, 30, 35)
    }
    
    txt_hook = TextClip(**txt_hook_params, method='label', horizontal_align='center', vertical_align='center')
    if txt_hook.w > hook_max_w:
        txt_hook = TextClip(**txt_hook_params, method='caption', size=(hook_max_w - 60, None), text_align='center', horizontal_align='center', vertical_align='center')
    
    txt_hook = apply_rounded_corners(txt_hook, radius=20)
    txt_hook = txt_hook.with_position(('center', safe_top)).with_duration(total_duration)
    txt_hook = txt_hook.with_effects([CrossFadeIn(duration=1.0)])
    
    # Update Safe Top (Bawah Hook)
    safe_top += txt_hook.h + 20

    # --- FITUR VISUAL TAMBAHAN (SOSMED) ---
    extra_clips = []
    
    # A. Informasi Surah
    if surah:
        txt_surah = TextClip(
            text=surah, font=os.path.join(BASE_DIR, 'OpenSauceOne-Bold.ttf'),
            font_size=24, color='white', bg_color='black', margin=(15, 10), method='label'
        )
        txt_surah = apply_rounded_corners(txt_surah, radius=10).with_opacity(0.8)
        txt_surah = txt_surah.with_position(('center', safe_top)).with_duration(total_duration)
        txt_surah = txt_surah.with_effects([CrossFadeIn(duration=1.2)])
        extra_clips.append(txt_surah)
        
        # Update Safe Top turun lagi (Bawah Surah)
        safe_top += txt_surah.h + 20

    # B. Audio Visualizer (Ditambahkan di atas Progress Bar)
    vis_h = 45
    vis_clip = create_audio_visualizer(final_audio, width=150, height=vis_h, color=(255, 215, 0))
    vis_y = video.h - 100
    vis_clip = vis_clip.with_position(('center', vis_y)).with_duration(total_duration)
    extra_clips.append(vis_clip)
    
    # Update Safe Bottom (Atas Visualizer)
    safe_bottom = vis_y - 20

    # C. Call to Action (CTA) - Muncul Dinamis di atas visualizer
    if cta:
        cta_duration = min(4.0, total_duration * 0.3)
        cta_start = total_duration - cta_duration
        txt_cta = TextClip(
            text=cta.upper(), font=os.path.join(BASE_DIR, 'Montserrat-Bold.ttf'),
            font_size=32, color='black', bg_color='#FFD700', margin=(20, 15), method='label'
        )
        txt_cta = apply_rounded_corners(txt_cta, radius=15)
        # Posisi di area bawah layar tapi di atas visualizer
        cta_y = safe_bottom - txt_cta.h
        txt_cta = txt_cta.with_position(('center', cta_y))
        txt_cta = txt_cta.with_start(cta_start).with_duration(cta_duration)
        txt_cta = txt_cta.with_effects([CrossFadeIn(duration=0.5), CrossFadeOut(duration=0.5)])
        extra_clips.append(txt_cta)
        
        # Update Safe Bottom (Atas CTA)
        safe_bottom = cta_y - 20

    # D. Progress Bar (Paling Bawah Frame)
    progress_height = 8
    prog_bg = ColorClip(size=(video.w, progress_height), color=(0, 0, 0)).with_opacity(0.4)
    prog_bg = prog_bg.with_position(('center', video.h - progress_height)).with_duration(total_duration)
    extra_clips.append(prog_bg)
    
    prog_bar = ColorClip(size=(video.w, progress_height), color=(255, 215, 0))
    prog_bar = prog_bar.with_duration(total_duration)
    prog_bar = prog_bar.with_position(lambda t: (int((t / total_duration) * video.w) - video.w, video.h - progress_height))
    extra_clips.append(prog_bar)

    # Menghitung Kapasitas Area Vertikal Tengah yang Tersisa (Ruang Aman dari tumpang tindih)
    available_height = safe_bottom - safe_top
    arab_max_h = max(100, int(available_height * 0.45))
    latin_max_h = max(50, int(available_height * 0.20))
    trans_max_h = max(50, int(available_height * 0.35))

    # 5. Create Verse Clips Sequentially
    all_text_clips = []
    # Offset waktu agar teks muncul mengikuti audio yang sekarang ada jedanya
    current_start = taawudz_duration + (gap_duration if taawudz_clip else 0.0)

    for ayat, trans, latin, a_clip in zip(list_ayats, list_translations, list_latins, audio_clips):
        duration = a_clip.duration

        # --- AUTOMATIC PAGING ---
        # Jika teks terlalu panjang, bagi menjadi beberapa "halaman" agar tetap terbaca profesional
        chars_per_page_arabic = 200
        chars_per_page_trans = 250

        num_pages = math.ceil(max(len(ayat) / chars_per_page_arabic, len(trans) / chars_per_page_trans))
        pages_a = split_text_to_pages(ayat, num_pages)
        pages_t = split_text_to_pages(trans, num_pages)
        pages_l = split_text_to_pages(latin, num_pages) if latin else [""] * num_pages
        page_duration = duration / num_pages

        for p_idx in range(num_pages):
            p_ayat = pages_a[p_idx]
            p_trans = pages_t[p_idx]
            p_latin = pages_l[p_idx]
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
                max_h=arab_max_h,
                stroke_color='#FFD700',
                stroke_width=1,
                text_align='center',
                margin=(20, 20),
                interline=20
            )

            # --- LATIN RENDERING (OPTIONAL) ---
            chars_per_line = max(25, int(45 * (video.w / 1080)))
            tx_l = None
            if p_latin:
                wrapped_latin = textwrap.fill(p_latin, width=chars_per_line)
                tx_l = create_scaled_text(
                    text=wrapped_latin,
                    font=os.path.join(BASE_DIR, 'Arial.ttf'),
                    initial_size=28,
                    color='#38BDF8', # Sky Blue modern untuk latin agar kontras dan memukau
                    max_w=int(video.w * 0.9),
                    max_h=latin_max_h,
                    stroke_color='black', # Stroke tebal untuk keterbacaan tingkat tinggi
                    stroke_width=2,
                    text_align='center',
                    margin=(20, 10),
                    interline=10
                )

            # --- TRANSLATION RENDERING ---
            wrapped_trans = textwrap.fill(p_trans, width=chars_per_line)

            tx_t = create_scaled_text(
                text=wrapped_trans,
                font=os.path.join(BASE_DIR, 'OpenSauceOne-Bold.ttf'),
                initial_size=35,
                color='white',
                max_w=int(video.w * 0.9),
                max_h=trans_max_h,
                stroke_color='black', # Tambahan stroke agar terjemahan tidak tenggelam di BG putih cerah
                stroke_width=1,
                text_align='center',
                margin=(20, 20),
                interline=10
            )

            # --- LAYOUTING & ALIGNMENT ---
            gap_arab_latin = 20 if tx_l else 40
            gap_latin_trans = 20

            v_height = tx_a.h
            if tx_l:
                v_height += gap_arab_latin + tx_l.h
            v_height += (gap_latin_trans if tx_l else gap_arab_latin) + tx_t.h

            # Teks dipusatkan secara dinamis di DALAM "Safe Area" (Tengah-tengah ruang aman)
            v_start_y = safe_top + (available_height - v_height) // 2

            # Penempatan posisi vertikal berurutan
            curr_y = v_start_y

            tx_a = tx_a.with_position(('center', curr_y)).with_start(p_start).with_duration(page_duration)
            tx_a = tx_a.with_effects([CrossFadeIn(duration=0.4), CrossFadeOut(duration=0.4)])
            curr_y += tx_a.h + gap_arab_latin

            clip_group = [tx_a]

            if tx_l:
                tx_l = tx_l.with_position(('center', curr_y)).with_start(p_start).with_duration(page_duration)
                tx_l = tx_l.with_effects([CrossFadeIn(duration=0.4), CrossFadeOut(duration=0.4)])
                clip_group.append(tx_l)
                curr_y += tx_l.h + gap_latin_trans

            tx_t = tx_t.with_position(('center', curr_y)).with_start(p_start).with_duration(page_duration)
            tx_t = tx_t.with_effects([CrossFadeIn(duration=0.4), CrossFadeOut(duration=0.4)])
            clip_group.append(tx_t)

            all_text_clips.extend(clip_group)

        # Durasi visual ayat + gap untuk ayat berikutnya
        current_start += duration + gap_duration

    # 6. Combine All
    # Overlay sudah di-bake ke background, jadi lebih sedikit layer = lebih cepat
    final_video = CompositeVideoClip([video, txt_watermark, txt_hook] + extra_clips + all_text_clips)

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
    content.add_argument("--latin", default="", help="Teks transliterasi latin (Opsional, gunakan | untuk memisahkan)")
    content.add_argument("--audio", required=True, help="Path lokal atau URL MP3 (Gunakan | untuk memisahkan)")

    assets = parser.add_argument_group('Aset & Styling')
    assets.add_argument("--bg", required=True, help="Path file video background (.mp4)")
    assets.add_argument("--hook", default="", help="Teks Hook/Judul di bagian atas")
    assets.add_argument("--watermark", default="", help="Teks watermark di kiri bawah")
    assets.add_argument("--overlay", default=0.3, type=float, help="Opacity overlay hitam (0.0 - 1.0, default: 0.3)")
    assets.add_argument("--taawudz",
                        default="https://cdn.equran.id/audio-partial/Abdullah-Al-Juhany/001000.mp3",
                        help="URL/path audio Ta'awudz (Audzubillah) di awal. Gunakan 'none' untuk skip.")
    assets.add_argument("--audio_bg", default="", help="Path atau URL Audio Background melodi/ambient (Opsional)")
    assets.add_argument("--surah", default="", help="Nama surah dan ayat (misal: Surah Al-Baqarah: 152)")
    assets.add_argument("--cta", default="", help="Teks Call to Action di akhir video (misal: Save untuk nanti)")
    assets.add_argument("--gap", default=0.0, type=float, help="Jeda antar ayat dalam detik (misal: 2.0 untuk mengecoh Content ID)")
    assets.add_argument("--pitch", default=1.0, type=float, help="Ubah pitch/speed audio murottal, misal 1.02 (+2%) atau 0.98 (-2%)")

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
        overlay_opacity=args.overlay,
        taawudz_url=args.taawudz,
        surah=args.surah,
        cta=args.cta,
        latin_texts=args.latin,
        audio_bg_url=args.audio_bg,
        gap_duration=args.gap,
        pitch_factor=args.pitch
    )
