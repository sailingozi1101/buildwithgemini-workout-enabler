import os
import sys
import time
import glob
import math
import struct
import wave
import subprocess
import asyncio
from playwright.async_api import async_playwright

ARTIFACT_DIR = "/config/.gemini/antigravity/brain/88c12093-0020-47e7-b85e-a677d3457bf0"
RAW_VIDEO_DIR = "/tmp/demo_raw"
AUDIO_PATH = "/tmp/lofi_music.wav"
FINAL_VIDEO_PATH = os.path.join(ARTIFACT_DIR, "workout_enabler_demo.mp4")

os.makedirs(RAW_VIDEO_DIR, exist_ok=True)
os.makedirs(ARTIFACT_DIR, exist_ok=True)


def generate_lofi_audio(filename=AUDIO_PATH, duration_sec=40):
    """Generates an upbeat lo-fi background track with jazzy chords and chill beat."""
    sample_rate = 44100
    num_samples = int(sample_rate * duration_sec)
    
    # 85 BPM beat timing
    bpm = 85
    seconds_per_beat = 60.0 / bpm
    samples_per_beat = int(sample_rate * seconds_per_beat)
    
    # Chord frequencies (Hz) - Cmaj7, Am7, Dm7, G7
    chords = [
        [261.63, 329.63, 392.00, 493.88],  # Cmaj7
        [220.00, 261.63, 329.63, 392.00],  # Am7
        [146.83, 174.61, 220.00, 261.63],  # Dm7
        [196.00, 246.94, 293.66, 349.23],  # G7
    ]
    
    out_samples = []
    
    for i in range(num_samples):
        t = i / sample_rate
        beat_num = int(t / seconds_per_beat)
        chord_idx = (beat_num // 8) % len(chords)
        current_chord = chords[chord_idx]
        
        # Chord synth (soft warm sine blend)
        chord_val = 0.0
        for freq in current_chord:
            chord_val += 0.15 * math.sin(2 * math.pi * freq * t)
            # Add warm octave harmonic
            chord_val += 0.05 * math.sin(2 * math.pi * (freq * 0.5) * t)
            
        # LFO filter modulation for lo-fi warmth
        lfo = 0.7 + 0.3 * math.sin(2 * math.pi * 0.2 * t)
        chord_val *= lfo
        
        # Beat pattern (Kick, Snare, Hi-hat)
        sample_in_beat = i % samples_per_beat
        beat_frac = sample_in_beat / samples_per_beat
        
        kick = 0.0
        snare = 0.0
        hihat = 0.0
        
        # Kick on beats 0 and 4 (in 8-beat measure)
        measure_beat = beat_num % 8
        if measure_beat in [0, 3, 4, 6]:
            kick_t = (i % (samples_per_beat * (1 if measure_beat != 3 else 0.5))) / sample_rate
            if kick_t < 0.12:
                kick = 0.4 * math.sin(2 * math.pi * (100 - 600 * kick_t) * kick_t) * math.exp(-30 * kick_t)
                
        # Snare on beats 2 and 6
        if measure_beat in [2, 6]:
            snare_t = beat_frac * seconds_per_beat
            if snare_t < 0.15:
                # White noise burst + tone
                noise = ((i * 1103515245 + 12345) & 0x7FFFFFFF) / 2147483648.0 - 0.5
                snare = (0.25 * noise + 0.1 * math.sin(2 * math.pi * 180 * snare_t)) * math.exp(-25 * snare_t)
                
        # Hi-hat on eighth notes
        eighth_step = (i % (samples_per_beat // 2)) / sample_rate
        if eighth_step < 0.04:
            noise = ((i * 1103515245 + 12345) & 0x7FFFFFFF) / 2147483648.0 - 0.5
            hihat = 0.08 * noise * math.exp(-80 * eighth_step)
            
        # Vinyl crackle ambiance
        crackle = 0.008 * (((i * 214013 + 2531011) & 0x7FFFFFFF) / 2147483648.0 - 0.5)
        
        mix = chord_val + kick + snare + hihat + crackle
        # Soft clipping
        mix = max(-0.95, min(0.95, mix))
        
        int_sample = int(mix * 32767)
        out_samples.append(struct.pack('<h', int_sample))
        
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b''.join(out_samples))
    print(f"Generated lo-fi audio track: {filename}")


async def record_demo():
    print("Starting Playwright demo recorder...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            record_video_dir=RAW_VIDEO_DIR,
            record_video_size={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        
        print("Navigating to http://localhost:8080...")
        await page.goto("http://localhost:8080")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(2.5)  # Showcase welcome banner gesture
        
        # --- PROMPT 1: What app does best ---
        prompt1 = "Plan a low-impact routine for joint sensitivity"
        print(f"Typing Prompt 1: '{prompt1}'...")
        input_elem = page.locator("#input")
        await input_elem.focus()
        for char in prompt1:
            await input_elem.type(char, delay=40)
            await asyncio.sleep(0.02)
            
        await asyncio.sleep(0.5)
        await page.click("button[type='submit']")
        
        # Wait for agent response to appear and finish loading
        print("Waiting for Agent response to Prompt 1...")
        await page.wait_for_function(
            "() => { const bubbles = document.querySelectorAll('.msg.agent .bubble'); return bubbles.length > 0 && !bubbles[bubbles.length - 1].textContent.includes('…'); }",
            timeout=45000
        )
        await asyncio.sleep(5)  # Pause to let user read A2UI plan
        
        # --- PROMPT 2: Richer prompt (tool call + image generation) ---
        prompt2 = "Get exercise guide for Dumbbell Bench Press and generate a visual"
        print(f"Typing Prompt 2: '{prompt2}'...")
        await input_elem.focus()
        for char in prompt2:
            await input_elem.type(char, delay=35)
            await asyncio.sleep(0.02)
            
        await asyncio.sleep(0.5)
        await page.click("button[type='submit']")
        
        print("Waiting for Agent response & generated image card...")
        await page.wait_for_function(
            "() => { const bubbles = document.querySelectorAll('.msg.agent .bubble'); return bubbles.length > 1 && !bubbles[bubbles.length - 1].textContent.includes('…'); }",
            timeout=60000
        )
        # Scroll down smooth to show generated image and guide
        await page.evaluate("document.getElementById('log').scrollTo({top: 9999, behavior: 'smooth'})")
        await asyncio.sleep(6)  # Pause to showcase generated image & guide
        
        print("Closing page and context to complete video recording...")
        await page.close()
        await context.close()
        await browser.close()


def merge_video_and_audio():
    print("Finding raw webm video...")
    video_files = glob.glob(os.path.join(RAW_VIDEO_DIR, "*.webm"))
    if not video_files:
        raise FileNotFoundError(f"No webm video files found in {RAW_VIDEO_DIR}")
    
    raw_video = video_files[0]
    print(f"Raw video file: {raw_video}")
    
    # Generate upbeat lo-fi audio
    generate_lofi_audio(AUDIO_PATH, duration_sec=35)
    
    # Run ffmpeg to mix video + lo-fi audio into final MP4 artifact
    cmd = [
        "ffmpeg", "-y",
        "-i", raw_video,
        "-i", AUDIO_PATH,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        FINAL_VIDEO_PATH
    ]
    print("Running ffmpeg:", " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("FFmpeg error:", res.stderr)
        raise RuntimeError(f"FFmpeg failed: {res.stderr}")
        
    print(f"SUCCESS! Demo video created at: {FINAL_VIDEO_PATH}")


if __name__ == "__main__":
    asyncio.run(record_demo())
    merge_video_and_audio()
