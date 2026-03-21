#!/usr/bin/env python3
"""
Nimbus Marketing Launch — One command to generate all marketing assets.
Run: python marketing/launch.py
"""

import subprocess
import sys
from pathlib import Path

MARKETING_DIR = Path(__file__).parent
PROJECT_DIR = MARKETING_DIR.parent
OUTPUT_DIR = MARKETING_DIR / "output"


def run_step(name, cmd):
    print(f"\n{'='*50}")
    print(f"  {name}")
    print(f"{'='*50}\n")
    result = subprocess.run(cmd, cwd=str(PROJECT_DIR))
    if result.returncode != 0:
        print(f"  FAILED: {name}")
        return False
    return True


def main():
    print("=" * 50)
    print("  NIMBUS MARKETING LAUNCH")
    print("=" * 50)

    # Step 1: Generate all written content
    if not run_step(
        "Generating marketing content (X thread, Reddit, video script)",
        [sys.executable, str(MARKETING_DIR / "content.py")]
    ):
        return

    # Step 2: Generate video
    if not run_step(
        "Generating faceless video (YouTube Short / TikTok)",
        [sys.executable, str(MARKETING_DIR / "video.py")]
    ):
        print("Video generation failed — continuing with text content only")

    # Step 3: Summary
    print("\n" + "=" * 50)
    print("  LAUNCH ASSETS READY")
    print("=" * 50)

    output_files = sorted(OUTPUT_DIR.glob("*"))
    for f in output_files:
        size = f.stat().st_size
        if size > 1_000_000:
            size_str = f"{size/1_000_000:.1f}MB"
        elif size > 1_000:
            size_str = f"{size/1_000:.1f}KB"
        else:
            size_str = f"{size}B"
        print(f"  {f.name:40s} {size_str}")

    print(f"\n  All files in: {OUTPUT_DIR}")
    print()
    print("  NEXT STEPS:")
    print("  1. Review content in marketing/output/")
    print("  2. Post X thread: copy from x_thread.txt")
    print("  3. Upload video: nimbus_short.mp4 to YouTube Shorts / TikTok")
    print("  4. Post Reddit: copy from r_ClaudeAI.txt and r_selfhosted.txt")
    print()


if __name__ == "__main__":
    main()
