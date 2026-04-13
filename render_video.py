import sys
import argparse
import textwrap
import os
import urllib.request
from moviepy import VideoFileClip, AudioFileClip, TextClip, CompositeVideoClip, concatenate_audioclips, ColorClip
from moviepy.video.fx import CrossFadeIn, CrossFadeOut
from arabic_reshaper import reshape
from bidi.algorithm import get_display
import json

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

def create_scaled_text(text, font, initial_size, color, max_w, max_h, **kwargs):
    """Membuat TextClip yang otomatis mengecil jika teks terlalu panjang/tinggi."""
    current_size = initial_size
    min_size = 15
    
    while current_size >= min_size:
        clip = TextClip(
            text=text, 
            font_size=current_size, 
            color=color, 
            font=font, 
            method='caption', 
            size=(max_w, None), 
            **kwargs
        )
        if clip.h <= max_h:
            return clip
        current_size -= 4  # Kurangi ukuran font secara bertahap
        
    # Jika sudah di ukuran minimal tetap tidak cukup
    return clip

def create_quran_video(ayat_texts, translations, audio_paths, bg_path, output_name, watermark, hook, overlay_opacity):
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

    # 2b. Tambahkan Overlay Hitam (Dimmer) agar teks lebih terbaca
    overlay = ColorClip(size=video.size, color=(0, 0, 0)).with_duration(total_duration).with_opacity(float(overlay_opacity))

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

        # --- ARABIC RENDERING ---
        # Gunakan wrap manual agar tidak melebihi lebar dan tidak terpotong di pinggir
        # Kita tidak menggunakan reshaper & bidi lagi karena sepertinya engine ImageMagick 
        # di sistem user sudah menanganinya, dan penambahan manual malah membuatnya error/hilang.
        arabic_width = max(20, int(35 * (video.w / 1080)))
        wrapped_ayat = textwrap.fill(ayat, width=arabic_width)
        
        # Arabic Clip - Dibatasi tinggi maks 40% video
        tx_a = create_scaled_text(
            text=wrapped_ayat, 
            font=os.path.join(BASE_DIR, 'UthmanicHafs.otf'),
            initial_size=80, 
            color='#FFD700',
            max_w=int(video.w * 0.9), # Lebar sedikit diperluas agar tidak terlalu sempit
            max_h=int(video.h * 0.40),
            stroke_color='#FFD700', 
            stroke_width=1,
            text_align='center', 
            margin=(20, 20), # Margin lebih besar (kiri-kanan) agar tidak terpotong
            interline=20
        )

        # --- TRANSLATION RENDERING ---
        # Wrap manual agar lebih pasti tidak terpotong
        chars_per_line = max(25, int(45 * (video.w / 1080)))
        wrapped_trans = textwrap.fill(trans, width=chars_per_line)
        
        # Translation Clip - Dibatasi tinggi maks 30% video
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

        tx_a = tx_a.with_position(('center', v_start_y)).with_start(current_start).with_duration(duration)
        tx_t = tx_t.with_position(('center', v_start_y + tx_a.h + gap)).with_start(current_start).with_duration(duration)

        # Transitions
        tx_a = tx_a.with_effects([CrossFadeIn(duration=0.5), CrossFadeOut(duration=0.5)])
        tx_t = tx_t.with_effects([CrossFadeIn(duration=0.5), CrossFadeOut(duration=0.5)])

        all_text_clips.extend([tx_a, tx_t])
        current_start += duration

    # 6. Combine All
    # Urutan layer: Background -> Overlay -> Watermark/Hook -> Ayat/Terjemahan
    final_video = CompositeVideoClip([video, overlay, txt_watermark, txt_hook] + all_text_clips)

    # Simpan di folder output jika path tidak mengandung folder
    if not os.path.dirname(output_name):
        output_name = os.path.join(output_dir, output_name)

    print(f"Rendering final video to: {output_name}...", file=sys.stderr)
    final_video.write_videofile(output_name, fps=24, codec='libx264', logger=None)

    # Berikan output JSON untuk n8n agar mudah di-parse
    result = {
        "status": "success",
        "output_file": output_name,
        "absolute_path": os.path.abspath(output_name),
        "duration": float(total_duration)
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
