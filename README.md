# Quran Video Generator for Shorts & Reels

A powerful and dynamic Python script to generate professional Quranic videos for social media (Shorts, Reels, TikTok). This tool handles multiple verses, automatic audio-text synchronization, professional typography, and dynamic backgrounds.

## Features

- **Sequential Verses:** Support multiple verses (`ayat`) in a single video.
- **Audio URLs:** Automatically download audio from URLs (e.g., equran.id).
- **Professional Typography:** Uses Uthmanic Hafs script and modern fonts.
- **Dynamic Hook:** Catchy title at the top with a semi-transparent plate.
- **Smart Wrapping:** Ensuring words aren't split across lines.
- **Automatic Transitions:** Smooth CrossFade transitions between verses.
- **Dimmer Overlay:** Dark overlay for better readability on bright backgrounds.

## Installation

1. Clone this repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Make sure you have the required fonts in the directory:
   - `UthmanicHafs.otf`
   - `Lora.ttf`
   - `OpenSauceOne-Bold.ttf`
   - `Arial.ttf`

## Usage

```bash
python3 render_video.py \
  --ayat "Ayat 1 | Ayat 2" \
  --trans "Translation 1 | Translation 2" \
  --audio "url_or_path1.mp3 | url_or_path2.mp3" \
  --bg "background_video.mp4" \
  --hook "CATCHY HOOK TITLE" \
  --watermark "@your_username" \
  --output "final_video.mp4" \
  --overlay 0.3
```

## License
MIT
