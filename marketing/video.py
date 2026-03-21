#!/usr/bin/env python3
"""
Nimbus Video Generator — Creates faceless YouTube Short / TikTok
Uses Pillow for frames + moviepy for video assembly + gTTS for voiceover.
"""

import json
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
from gtts import gTTS

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
LOGO_PATH = SCRIPT_DIR / "assets" / "logo_lagoontech.jpg"

# Video dimensions (9:16 for Shorts/TikTok)
WIDTH = 1080
HEIGHT = 1920

# Try to find a good font
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]

FONT_PATHS_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
]


def find_font(paths, size=72):
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def create_frame(scene, frame_path):
    """Create a single frame image for a scene."""
    bg_color = hex_to_rgb(scene["bg_color"])
    text_color = hex_to_rgb(scene["text_color"])

    img = Image.new("RGB", (WIDTH, HEIGHT), bg_color)
    draw = ImageDraw.Draw(img)

    # Main text
    main_font = find_font(FONT_PATHS, 80)
    sub_font = find_font(FONT_PATHS_REGULAR, 48)

    main_text = scene["text"]
    sub_text = scene.get("subtext", "")

    # Center main text
    bbox = draw.multiline_textbbox((0, 0), main_text, font=main_font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (WIDTH - text_w) // 2
    y = (HEIGHT // 2) - text_h - 40

    draw.multiline_text((x, y), main_text, fill=text_color, font=main_font, align="center")

    # Subtext below
    if sub_text:
        sub_color = tuple(min(255, c + 60) for c in bg_color)  # slightly lighter than bg
        if sum(bg_color) < 200:
            sub_color = (160, 160, 170)

        bbox_sub = draw.multiline_textbbox((0, 0), sub_text, font=sub_font)
        sub_w = bbox_sub[2] - bbox_sub[0]
        sub_x = (WIDTH - sub_w) // 2
        sub_y = y + text_h + 60

        draw.multiline_text(
            (sub_x, sub_y), sub_text, fill=sub_color, font=sub_font, align="center"
        )

    # Branding bar at bottom with logo
    bar_h = 100
    bar_color = tuple(min(255, c + 15) for c in bg_color)
    draw.rectangle([(0, HEIGHT - bar_h), (WIDTH, HEIGHT)], fill=bar_color)

    # Add logo to branding bar
    logo_x_offset = 20
    if LOGO_PATH.exists():
        logo = Image.open(LOGO_PATH)
        logo_height = bar_h - 20
        logo_ratio = logo_height / logo.height
        logo_width = int(logo.width * logo_ratio)
        logo = logo.resize((logo_width, logo_height), Image.LANCZOS)
        logo_y = HEIGHT - bar_h + 10
        img.paste(logo, (logo_x_offset, logo_y))
        logo_x_offset = logo_x_offset + logo_width + 15

    brand_font = find_font(FONT_PATHS_REGULAR, 26)
    brand_text = "LAGOONTECH SYSTEMS — github.com/Bigabou007-dev/nimbus"
    draw.text(
        (logo_x_offset, HEIGHT - bar_h + 35),
        brand_text, fill=(120, 120, 130), font=brand_font
    )

    img.save(frame_path)
    return frame_path


def generate_voiceover(scenes, audio_dir):
    """Generate TTS voiceover for each scene."""
    audio_paths = []
    for i, scene in enumerate(scenes):
        text = scene["text"].replace("\n", " ")
        if scene.get("subtext"):
            text += ". " + scene["subtext"].replace("\n", " ")

        audio_path = os.path.join(audio_dir, f"scene_{i}.mp3")
        tts = gTTS(text=text, lang="en", slow=False)
        tts.save(audio_path)
        audio_paths.append(audio_path)

    return audio_paths


def build_video(scenes, output_path, with_audio=True):
    """Assemble scenes into a video."""
    print("Generating frames...")

    with tempfile.TemporaryDirectory() as tmpdir:
        clips = []

        # Generate audio if requested
        audio_paths = []
        if with_audio:
            print("Generating voiceover...")
            audio_paths = generate_voiceover(scenes, tmpdir)

        for i, scene in enumerate(scenes):
            # Create frame
            frame_path = os.path.join(tmpdir, f"frame_{i}.png")
            create_frame(scene, frame_path)

            duration = scene["duration"]

            # If we have audio, adjust duration to match
            if with_audio and i < len(audio_paths):
                audio_clip = AudioFileClip(audio_paths[i])
                # Use the longer of scene duration or audio duration + 0.5s padding
                duration = max(duration, audio_clip.duration + 0.5)
                img_clip = ImageClip(frame_path, duration=duration)
                img_clip = img_clip.with_audio(audio_clip)
            else:
                img_clip = ImageClip(frame_path, duration=duration)

            clips.append(img_clip)
            print(f"  Scene {i+1}/{len(scenes)}: {duration:.1f}s")

        print("Assembling video...")
        final = concatenate_videoclips(clips, method="compose")
        final.write_videofile(
            str(output_path),
            fps=24,
            codec="libx264",
            audio_codec="aac",
            logger=None,
        )

        # Cleanup clips
        for clip in clips:
            clip.close()
        final.close()

    print(f"Video saved to {output_path}")
    return output_path


def main():
    # Load script
    script_path = OUTPUT_DIR / "video_script.json"
    if not script_path.exists():
        print("Run content.py first to generate the video script.")
        return

    scenes = json.loads(script_path.read_text())

    # Build video with voiceover
    output_path = OUTPUT_DIR / "nimbus_short.mp4"
    build_video(scenes, output_path, with_audio=True)

    # Also build silent version (for TikTok where people add their own audio)
    silent_path = OUTPUT_DIR / "nimbus_short_silent.mp4"
    build_video(scenes, silent_path, with_audio=False)

    total_duration = sum(s["duration"] for s in scenes)
    print(f"\nDone! ~{total_duration}s video generated.")
    print(f"  With voiceover: {output_path}")
    print(f"  Silent version: {silent_path}")


if __name__ == "__main__":
    main()
