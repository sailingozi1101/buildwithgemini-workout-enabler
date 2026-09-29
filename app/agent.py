# ruff: noqa
# Copyright 2026 Google LLC

import os
import json
import datetime
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.memory import VertexAiMemoryBankService
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.genai import types
from google import genai
from google.cloud import firestore, storage

from a2ui.schema.manager import A2uiSchemaManager
from a2ui.basic_catalog.provider import BasicCatalog
from .a2ui_utils import a2ui_callback

# Hardcode project ID as string for Firestore & Storage clients
PROJECT_ID = "qwiklabs-gcp-02-ff4db1ff689a"
import logging

logger = logging.getLogger(__name__)
GCS_BUCKET_NAME = "workout-enabler-media-qwiklabs-gcp-02-ff4db1ff689a"
MEMORY_BANK_ID = "4161263933283368960"


async def generate_memories_callback(callback_context: CallbackContext):
    """WRITE: after each turn, send the session to Memory Bank for durable memory extraction."""
    try:
        await callback_context.add_session_to_memory()
    except Exception as e:
        logger.warning(f"add_session_to_memory failed or service unconfigured: {e}")
    return None


def memory_bank_service_builder():
    """Builds a VertexAiMemoryBankService pointing at our deployed Agent Engine Memory Bank."""
    return VertexAiMemoryBankService(
        project=PROJECT_ID,
        location="us-central1",
        agent_engine_id=MEMORY_BANK_ID,
    )


def get_code_executor() -> AgentEngineSandboxCodeExecutor:
    """Creates an AgentEngineSandboxCodeExecutor for safe Python code execution in Agent Platform sandbox environments.

    Loads agent_engine_resource_name or sandbox_resource_name from deployment_metadata.json if available.
    """
    os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
    os.environ["GOOGLE_CLOUD_LOCATION"] = "us-central1"

    agent_engine_name = os.getenv("AGENT_ENGINE_RESOURCE_NAME")
    sandbox_name = os.getenv("SANDBOX_RESOURCE_NAME")

    # Search for deployment_metadata.json in workspace
    metadata_locations = [
        "deployment_metadata.json",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "deployment_metadata.json"),
        os.path.join(os.path.dirname(__file__), "deployment_metadata.json"),
    ]

    for path in metadata_locations:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    meta = json.load(f)
                    if not agent_engine_name:
                        agent_engine_name = (
                            meta.get("agent_engine_resource_name")
                            or meta.get("remote_agent_runtime_id")
                        )
                    if not sandbox_name:
                        sandbox_name = (
                            meta.get("sandbox_resource_name")
                            or meta.get("sandbox_name")
                        )
            except Exception as e:
                print(f"Warning reading deployment metadata from {path}: {e}")

    return AgentEngineSandboxCodeExecutor(
        sandbox_resource_name=sandbox_name,
        agent_engine_resource_name=agent_engine_name,
    )


def get_firestore_client() -> firestore.Client:
    """Returns a Firestore client initialized with hardcoded project ID."""
    return firestore.Client(project=PROJECT_ID)


def list_workout_routines(target_muscle: str = "") -> list[dict]:
    """Retrieves workout routines stored in Firestore database.

    Args:
        target_muscle: Optional filter for muscle group or focus area (e.g. 'Chest', 'Legs', 'Full Body').

    Returns:
        List of matching workout routine dictionaries.
    """
    db = get_firestore_client()
    routines_ref = db.collection("workout_routines")
    docs = routines_ref.stream()

    results = []
    for doc in docs:
        data = doc.to_dict()
        if not target_muscle or target_muscle.lower() in data.get("target_muscle", "").lower():
            results.append(data)
    return results


def log_workout(exercise_name: str, sets: int, reps: int, weight_lbs: float, notes: str = "") -> dict:
    """Logs a completed workout session to Firestore.

    Args:
        exercise_name: Name of the exercise performed (e.g. 'Bench Press', 'Squat').
        sets: Number of sets performed.
        reps: Repetitions per set.
        weight_lbs: Weight used in pounds.
        notes: Optional feedback or notes on how the workout felt.

    Returns:
        Dictionary confirming log record details.
    """
    db = get_firestore_client()
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    log_data = {
        "timestamp_iso": now_iso,
        "exercise_name": exercise_name,
        "sets": int(sets),
        "reps": int(reps),
        "weight_lbs": float(weight_lbs),
        "notes": notes,
    }

    doc_ref = db.collection("workout_logs").document()
    doc_ref.set(log_data)

    log_data["log_id"] = doc_ref.id
    return {"status": "success", "message": "Workout logged successfully!", "log": log_data}


def get_workout_history(limit: int = 10) -> list[dict]:
    """Retrieves past workout logs from Firestore.

    Args:
        limit: Maximum number of recent workout entries to return (default: 10).

    Returns:
        List of logged workout session dictionaries.
    """
    db = get_firestore_client()
    logs_ref = db.collection("workout_logs")
    docs = logs_ref.stream()

    logs = [doc.to_dict() for doc in docs]
    logs.sort(key=lambda x: x.get("timestamp_iso", ""), reverse=True)
    return logs[:limit]


def save_user_profile(rest_recovery_days: int = 2, fitness_goals: str = "", physical_limitations: str = "") -> dict:
    """Saves user recovery preferences, fitness goals, and physical limitations to Firestore and user profile.

    Args:
        rest_recovery_days: Days/time needed for user to feel fully rested to resume workouts (e.g. 1 to 3 days).
        fitness_goals: Brief description of user fitness goals (e.g. 'Build strength', 'Lose weight').
        physical_limitations: Any physical limitations, injuries, joint issues, or health constraints (e.g. 'lower back injury', 'knee arthritis', 'shoulder impingement').

    Returns:
        Dictionary confirming updated profile details.
    """
    db = get_firestore_client()
    profile_data = {
        "rest_recovery_days": int(rest_recovery_days),
        "fitness_goals": fitness_goals,
        "physical_limitations": physical_limitations,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    db.collection("user_profiles").document("default_user").set(profile_data, merge=True)
    return {"status": "success", "profile": profile_data}


def check_inactivity_status() -> str:
    """Checks how long it has been since the user's last logged workout and evaluates recovery status.

    Returns:
        Summary message indicating hours/days since last workout and whether a reminder or rest is recommended.
    """
    db = get_firestore_client()
    logs = get_workout_history(limit=1)

    if not logs:
        return "No workouts recorded yet. Prompt the user to start their first workout session!"

    last_log = logs[0]
    last_time_str = last_log.get("timestamp_iso")
    if not last_time_str:
        return "Could not parse timestamp of last workout."

    last_time = datetime.datetime.fromisoformat(last_time_str)
    now = datetime.datetime.now(datetime.timezone.utc)
    hours_elapsed = (now - last_time).total_seconds() / 3600.0

    profile_doc = db.collection("user_profiles").document("default_user").get()
    rest_days = 2
    if profile_doc.exists:
        rest_days = profile_doc.to_dict().get("rest_recovery_days", 2)

    rest_hours_target = rest_days * 24

    if hours_elapsed > 48:
        return (
            f"It has been {hours_elapsed:.1f} hours (>48 hours) since the user's last workout ({last_log.get('exercise_name')}). "
            f"User preferred recovery is {rest_days} day(s) ({rest_hours_target}h). Gently remind the user to resume working out if rested!"
        )
    else:
        return f"User logged a workout {hours_elapsed:.1f} hours ago. Recovery is on track."


def calculate_fitness_metrics(weight_lbs: float, reps: int, age: int = 30, resting_hr: int = 60) -> dict:
    """Calculates 1-Rep Max (1RM), volume load, and Karvonen heart rate training zones.

    Args:
        weight_lbs: Weight lifted in pounds.
        reps: Number of repetitions completed.
        age: User age in years (default: 30).
        resting_hr: Resting heart rate in beats per minute (default: 60).

    Returns:
        Dictionary containing calculated 1RM, volume load, max heart rate, and target heart rate zones.
    """
    # Epley formula for 1-Rep Max
    one_rep_max = round(weight_lbs * (1.0 + reps / 30.0), 1) if reps > 1 else weight_lbs
    volume_load = round(weight_lbs * reps, 1)

    max_hr = 220 - age
    hr_reserve = max_hr - resting_hr
    mod_zone_min = round(resting_hr + 0.60 * hr_reserve)
    mod_zone_max = round(resting_hr + 0.70 * hr_reserve)
    vig_zone_min = round(resting_hr + 0.70 * hr_reserve)
    vig_zone_max = round(resting_hr + 0.85 * hr_reserve)

    return {
        "estimated_1rm_lbs": one_rep_max,
        "volume_load_lbs": volume_load,
        "max_heart_rate": max_hr,
        "target_hr_zones": {
            "moderate_burn_bpm": f"{mod_zone_min} - {mod_zone_max}",
            "vigorous_cardio_bpm": f"{vig_zone_min} - {vig_zone_max}",
        },
    }


def generate_exercise_visual(exercise_name: str, motivational_quote: str = "Keep pushing forward!") -> dict:
    """Generates an exercise visual card and uploads it to Cloud Storage.

    Args:
        exercise_name: Name of the exercise (e.g. 'Squat', 'Bench Press').
        motivational_quote: Short motivational message.

    Returns:
        Dictionary containing the public URL of the uploaded exercise graphic.
    """
    clean_name = exercise_name.strip().title()
    filename = f"visual_{clean_name.lower().replace(' ', '_')}.svg"

    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="350" viewBox="0 0 600 350">
  <rect width="600" height="350" rx="16" fill="#0f172a"/>
  <circle cx="300" cy="140" r="70" fill="#2563eb" opacity="0.3"/>
  <circle cx="300" cy="140" r="45" fill="#3b82f6"/>
  <text x="300" y="148" font-family="system-ui, sans-serif" font-size="22" font-weight="bold" fill="#ffffff" text-anchor="middle">💪 {clean_name.upper()}</text>
  <text x="300" y="250" font-family="system-ui, sans-serif" font-size="18" font-style="italic" fill="#93c5fd" text-anchor="middle">"{motivational_quote}"</text>
  <text x="300" y="300" font-family="system-ui, sans-serif" font-size="14" fill="#64748b" text-anchor="middle">Workout Enabler Media Asset • GCP Cloud Storage</text>
</svg>"""

    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(svg_content, content_type="image/svg+xml")

    public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
    return {
        "status": "success",
        "exercise": clean_name,
        "public_image_url": public_url,
    }


EXERCISE_GUIDES = {
    "bench press": {
        "steps": [
            "1. Setup: Lie flat on the bench with feet firm on the floor and grip barbell slightly wider than shoulder-width.",
            "2. Unrack: Unrack barbell and stabilize directly over your chest with arms fully extended.",
            "3. Lowering: Inhale and lower the barbell in a controlled motion until it lightly touches your mid-chest.",
            "4. Drive: Exhale and press the barbell up explosively to top position while keeping shoulders retracted."
        ],
        "key_tips": "Keep shoulder blades pinched together and maintain a stable arch in your lower back.",
        "target_muscles": "Chest (Pectoralis Major), Shoulders (Anterior Deltoids), Triceps"
    },
    "squat": {
        "steps": [
            "1. Stance: Stand tall with feet shoulder-width apart, toes pointed slightly outward.",
            "2. Descent: Inhale, hinge at your hips and bend knees as if sitting into a deep chair.",
            "3. Depth: Lower until your thighs are at least parallel to the floor with chest proud.",
            "4. Ascent: Exhale and drive firmly through your heels to return to standing position."
        ],
        "key_tips": "Keep your chest up and ensure knees track over your toes without caving in.",
        "target_muscles": "Quadriceps, Hamstrings, Glutes, Core"
    },
    "overhead shoulder press": {
        "steps": [
            "1. Setup: Stand tall holding dumbbells or barbell at collarbone height with an overhand grip.",
            "2. Core Brace: Tighten your core and glutes to lock your torso in place.",
            "3. Drive: Exhale and press the weight straight overhead until elbows lock out.",
            "4. Lowering: Lower the weight back down smoothly under control to collarbone level."
        ],
        "key_tips": "Do not arch your lower back excessively; keep your core engaged throughout.",
        "target_muscles": "Shoulders (Deltoids), Upper Triceps, Core"
    },
    "tricep dips": {
        "steps": [
            "1. Setup: Mount parallel bars with arms extended and torso upright.",
            "2. Lowering: Inhale and lower your body by bending elbows until upper arms are parallel to the floor.",
            "3. Drive: Exhale and press hard through your hands to lock out arms at the top."
        ],
        "key_tips": "Keep elbows tucked close to your torso; avoid letting them flare outward.",
        "target_muscles": "Triceps Brachii, Lower Chest, Front Shoulders"
    },
    "push-ups": {
        "steps": [
            "1. Setup: Begin in a high plank position with hands shoulder-width apart and feet together.",
            "2. Lowering: Inhale and lower your chest until it nearly touches the floor.",
            "3. Drive: Exhale and push through your palms to return to full arm lockout."
        ],
        "key_tips": "Maintain a rigid plank line from head to heels throughout the motion.",
        "target_muscles": "Chest, Shoulders, Triceps, Core"
    }
}


async def get_exercise_guide(exercise_name: str, tool_context: ToolContext = None) -> dict:
    """Provides step-by-step form instructions, safety tips, target muscles, and an inline visual image for an exercise.

    Args:
        exercise_name: Name of the exercise (e.g. 'Bench Press', 'Squat', 'Push-ups', 'Overhead Press', 'Tricep Dips').
        tool_context: ADK ToolContext supplied automatically by the agent runtime.

    Returns:
        Dictionary containing step-by-step instructions, safety tips, target muscles, and inline image HTML/Markdown tags.
    """
    clean_key = exercise_name.strip().lower()
    guide_data = EXERCISE_GUIDES.get(clean_key, {
        "steps": [
            f"1. Setup: Position body in proper starting posture for {exercise_name.title()}.",
            "2. Execution: Move through full range of motion under strict control.",
            "3. Breath: Inhale during eccentric phase, exhale on concentric effort.",
            "4. Return: Re-stabilize smoothly at top starting position."
        ],
        "key_tips": "Prioritize strict form over heavy weight. Stop immediately if experiencing sharp discomfort.",
        "target_muscles": "Target muscle groups for " + exercise_name.title()
    })

    # Call AI image generation tool so image is saved to Playground Artifacts panel & uploaded to GCS
    img_res = await generate_workout_image(
        prompt=f"A high-quality athletic illustration demonstrating proper exercise form for {exercise_name.title()}",
        tool_context=tool_context
    )

    pub_url = img_res.get("public_url", "")
    return {
        "exercise_name": exercise_name.strip().title(),
        "steps": guide_data["steps"],
        "key_tips": guide_data["key_tips"],
        "target_muscles": guide_data["target_muscles"],
        "public_image_url": pub_url,
        "inline_html_image": f'<img src="{pub_url}" width="100%" alt="{exercise_name.title()} Guide" />',
        "inline_markdown_image": f'![{exercise_name.title()} Guide]({pub_url})',
    }


def schedule_inactivity_reminder(hours_from_now: int = 48) -> dict:
    """Schedules a workout reminder prompt for the user after a given rest interval.

    Args:
        hours_from_now: Number of hours to wait before triggering the reminder (default: 48).

    Returns:
        Dictionary confirming the scheduled reminder record.
    """
    db = get_firestore_client()
    now = datetime.datetime.now(datetime.timezone.utc)
    target_time = now + datetime.timedelta(hours=int(hours_from_now))

    reminder_data = {
        "scheduled_for_iso": target_time.isoformat(),
        "created_at_iso": now.isoformat(),
        "hours_interval": int(hours_from_now),
        "status": "PENDING",
        "message": f"Time to resume your workout routine after {hours_from_now} hours of recovery!",
    }

    doc_ref = db.collection("workout_reminders").document()
    doc_ref.set(reminder_data)

    return {
        "status": "success",
        "reminder_id": doc_ref.id,
        "scheduled_time_utc": target_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "message": f"Reminder successfully scheduled for {hours_from_now} hours from now.",
    }


def search_public_exercise_db(search_term: str = "") -> dict:
    """Searches the open-source Wger Public Workout & Exercise Database API (https://wger.de) for real exercise definitions.

    Args:
        search_term: Search query or keyword (e.g. 'Swing', 'Press', 'Adduction', 'Squat').

    Returns:
        Dictionary containing matching exercise results from the Wger public API.
    """
    import os, json, urllib.request, re

    api_key = os.getenv("WGER_API_KEY", "")
    url = "https://wger.de/api/v2/exerciseinfo/?language=2&limit=25"
    headers = {"User-Agent": "WorkoutEnablerApp/1.0"}
    if api_key:
        headers["Authorization"] = f"Token {api_key}"

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        matches = []
        term_lower = search_term.strip().lower()
        for item in data.get("results", []):
            for trans in item.get("translations", []):
                if trans.get("language") == 2:
                    name = trans.get("name", "")
                    desc_raw = trans.get("description", "")
                    clean_desc = re.sub(r"<[^>]+>", "", desc_raw).strip()
                    if not term_lower or term_lower in name.lower() or term_lower in clean_desc.lower():
                        matches.append({
                            "id": item.get("id"),
                            "name": name,
                            "description": clean_desc[:250] if clean_desc else "No description available.",
                        })

        return {
            "status": "success",
            "api_source": "Wger Public Workout Database API (https://wger.de)",
            "query": search_term,
            "count": len(matches),
            "exercises": matches[:5]
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to fetch from Wger API: {str(e)}"}


async def generate_workout_image(prompt: str, tool_context: ToolContext = None) -> dict:
    """Generates an image for a workout, exercise, or fitness theme using gemini-3.1-flash-lite-image in the global region.

    Saves the image with tool_context.save_artifact for the Playground's Artifacts panel,
    and uploads the image bytes directly to the public Cloud Storage bucket.

    Args:
        prompt: Description of the workout or exercise image to generate.
        tool_context: ADK ToolContext supplied automatically by the agent runtime.

    Returns:
        Dictionary containing the public Cloud Storage https URL of the generated image.
    """
    import asyncio
    genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
    res = genai_client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=prompt,
    )

    part = res.candidates[0].content.parts[0]
    image_bytes = part.inline_data.data
    mime_type = part.inline_data.mime_type or "image/jpeg"

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"workout_image_{timestamp}.jpg"

    if tool_context is not None:
        try:
            artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            save_res = tool_context.save_artifact(filename=filename, artifact=artifact_part)
            if asyncio.iscoroutine(save_res):
                await save_res
        except Exception as e:
            print(f"Artifact save notification: {e}")

    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(image_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
    return {
        "status": "success",
        "prompt": prompt,
        "filename": filename,
        "public_url": public_url,
        "inline_html_image": f'<img src="{public_url}" width="100%" alt="{prompt}" />',
        "inline_markdown_image": f'![{prompt}]({public_url})',
    }


async def generate_exercise_demo_video(prompt: str, tool_context: ToolContext = None) -> dict:
    """Generates a short exercise demonstration video using Google's Omni model (gemini-omni-flash-preview) in the global region.

    Saves the video with tool_context.save_artifact for the Playground's Artifacts panel,
    and uploads the video bytes directly to the public Cloud Storage bucket.

    Args:
        prompt: Description of the exercise or workout movement to generate as a video.
        tool_context: ADK ToolContext supplied automatically by the agent runtime.

    Returns:
        Dictionary containing the public Cloud Storage https URL of the generated video.
    """
    import base64
    import asyncio

    # Initialize Google GenAI client pointing to global region
    genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")

    # Call the Interactions API with Google's Omni model
    interaction = genai_client.interactions.create(
        model="gemini-omni-flash-preview",
        input=prompt,
    )

    # Extract raw video bytes in memory
    raw_data = getattr(interaction.output_video, "data", None)
    if isinstance(raw_data, str):
        video_bytes = base64.b64decode(raw_data)
    elif isinstance(raw_data, bytes):
        video_bytes = raw_data
    else:
        video_bytes = base64.b64decode(str(raw_data))

    mime_type = getattr(interaction.output_video, "mime_type", None) or "video/mp4"

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"exercise_video_{timestamp}.mp4"

    # 1. Save artifact for Playground Artifacts panel
    if tool_context is not None:
        try:
            artifact_part = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
            save_res = tool_context.save_artifact(filename=filename, artifact=artifact_part)
            if asyncio.iscoroutine(save_res):
                await save_res
        except Exception as e:
            logger.warning(f"Artifact save notification failed: {e}")

    # 2. Upload video bytes to public Cloud Storage bucket
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(video_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{filename}"
    return {
        "status": "success",
        "prompt": prompt,
        "filename": filename,
        "public_url": public_url,
        "video_url": public_url,
        "message": f"Successfully generated exercise demonstration video for '{prompt}'.",
    }


async def generate_personalized_training_plan(
    age: int,
    weight_lbs: float,
    gender: str,
    fitness_goal: str = "general fitness",
    physical_limitations: str = "",
    experience_level: str = "intermediate",
    tool_context: ToolContext = None,
) -> dict:
    """Generates a customized workout training plan tailored specifically to the user's age, weight, gender, and physical limitations.

    Args:
        age: User's age in years (e.g. 28, 45, 60).
        weight_lbs: User's weight in pounds (e.g. 155.0, 185.0).
        gender: Gender identity/biology for physiological baselines ('male', 'female', 'non-binary', or 'other').
        fitness_goal: Primary fitness goal ('strength', 'hypertrophy', 'fat loss', 'general fitness', 'endurance').
        physical_limitations: Any injuries or constraints (e.g. 'lower back pain', 'knee arthritis', 'shoulder impingement').
        experience_level: Training experience level ('beginner', 'intermediate', 'advanced').
        tool_context: ADK ToolContext supplied automatically by the agent runtime.

    Returns:
        Dictionary containing personalized weekly workout schedule, volume targets, macro guidelines, and plan artwork.
    """
    weight_kg = weight_lbs / 2.20462
    gender_clean = gender.strip().lower()

    # BMR & Caloric Baselines (Mifflin-St Jeor Formula)
    if "female" in gender_clean or "woman" in gender_clean:
        bmr = 10 * weight_kg + 6.25 * 162 - 5 * age - 161
        max_hr = round(206 - (0.88 * age))
    else:  # male / default
        bmr = 10 * weight_kg + 6.25 * 175 - 5 * age + 5
        max_hr = 220 - age

    daily_protein_g = round(weight_lbs * (0.9 if "female" in gender_clean else 1.0))

    # Determine split & frequency tailored to age and physical limitations
    limits_lower = physical_limitations.strip().lower() if physical_limitations else ""

    if "back" in limits_lower or "spine" in limits_lower:
        freq = "Joint & Spine-Friendly Modified Split"
        recovery_hours = 48
        routine_schedule = {
            "Day 1": "Chest & Upper Back (Chest Supported Dumbbell Press, Seated Cable Rows - 3x10-12 reps)",
            "Day 2": "Rest & Spine Decompression / Gentle Mobility",
            "Day 3": "Legs & Core (Leg Press / Belt Squats, Glute Bridges, Bird-Dogs - 3x10-12 reps)",
            "Day 4": "Rest & Low-Impact Swimming / Walking",
            "Day 5": "Shoulders & Arms (Seated Lateral Raises, Cable Face Pulls, Bicep Curls - 3x12-15 reps)",
            "Days 6-7": "Complete Recovery & Rest",
        }
    elif "knee" in limits_lower or "joint" in limits_lower:
        freq = "Low-Impact Knee-Safe Split"
        recovery_hours = 48
        routine_schedule = {
            "Day 1": "Upper Body Push & Pull (Chest Press, Lat Pulldowns, Dumbbell Rows - 3x10-12 reps)",
            "Day 2": "Rest & Water Aerobics / Swimming",
            "Day 3": "Hips, Glutes & Hamstrings (Glute Bridges, Roman Chair Extensions, Calves - 3x12 reps)",
            "Day 4": "Rest & Upper Body Core Mobility",
            "Day 5": "Upper Body & Arms (Overhead Press / Machine Dips, Bicep Curls - 3x10-12 reps)",
            "Days 6-7": "Complete Joint Recovery",
        }
    elif age < 30:
        freq = "4-5 Days/Week Intensive Split"
        recovery_hours = 24
        routine_schedule = {
            "Day 1": "Upper Body Power (Bench Press, Overhead Press, Rows, Dips - 4x6-8 reps)",
            "Day 2": "Lower Body Hypertrophy (Squats, Roman Leg Curls, Calves - 4x8-12 reps)",
            "Day 3": "Active Recovery / Light Mobility & Core",
            "Day 4": "Push & Core (Push-ups, Dumbbell Press, Triceps - 3x10-15 reps)",
            "Day 5": "Pull & Legs (Pull-ups, Barbell Rows, Lunges - 4x8-10 reps)",
            "Days 6-7": "Rest & Full Muscle Recovery",
        }
    elif age <= 50:
        freq = "3-4 Days/Week Balanced Split"
        recovery_hours = 48
        routine_schedule = {
            "Day 1": "Push & Core Focus (Bench Press, Overhead Press, Tricep Dips - 3x8-10 reps)",
            "Day 2": "Rest & Active Walk/Mobility",
            "Day 3": "Pull & Back Focus (Barbell Rows, Lat Pulldowns, Bicep Curls - 3x10-12 reps)",
            "Day 4": "Rest / Zone 2 Cardio",
            "Day 5": "Legs & Stability (Squats, Lunges, Glute Bridges - 3x10-12 reps)",
            "Days 6-7": "Complete Rest & Muscle Recovery",
        }
    else:
        freq = "3 Days/Week Joint-Friendly Full Body Split"
        recovery_hours = 48
        routine_schedule = {
            "Day 1": "Full Body Strength A (Goblet Squats, Dumbbell Press, Lat Rows - 3x10-12 reps)",
            "Day 2": "Rest & Light Stretching",
            "Day 3": "Full Body Strength B (Leg Press, Overhead Press, Cable Rows - 3x10-12 reps)",
            "Day 4": "Rest & Low-Impact Cardio (Swimming / Cycling)",
            "Day 5": "Full Body Stability & Core (Planks, Step-ups, Dumbbell Curls - 3x12-15 reps)",
            "Days 6-7": "Complete Recovery & Joint Rest",
        }

    # Generate custom training plan artwork via AI image generator
    prompt = (
        f"A professional athletic training plan schedule card for a {age} year old {gender_clean} "
        f"weighing {weight_lbs} lbs focusing on {fitness_goal}" +
        (f" with physical considerations for {physical_limitations}" if physical_limitations else "") +
        ", modern sleek fitness visual"
    )
    img_res = await generate_workout_image(prompt=prompt, tool_context=tool_context)
    pub_url = img_res.get("public_url", "")

    # Save to user profile in Firestore
    try:
        db = get_firestore_client()
        db.collection("user_profiles").document("default_user").set(
            {
                "age": int(age),
                "weight_lbs": float(weight_lbs),
                "gender": gender,
                "fitness_goal": fitness_goal,
                "physical_limitations": physical_limitations,
                "experience_level": experience_level,
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            merge=True,
        )
    except Exception as e:
        print(f"Firestore update warning: {e}")

    return {
        "status": "success",
        "user_profile": {
            "age": age,
            "weight_lbs": weight_lbs,
            "gender": gender.title(),
            "fitness_goal": fitness_goal.title(),
            "physical_limitations": physical_limitations if physical_limitations else "None specified",
            "experience_level": experience_level.title(),
        },
        "personalized_metrics": {
            "estimated_bmr_kcal": round(bmr),
            "daily_protein_target_g": daily_protein_g,
            "max_heart_rate_bpm": max_hr,
            "recommended_recovery_window_hours": recovery_hours,
        },
        "training_plan": {
            "split_name": freq,
            "weekly_schedule": routine_schedule,
        },
        "plan_visual_url": pub_url,
        "inline_html_image": f'<img src="{pub_url}" width="100%" alt="Personalized Training Plan" />',
        "inline_markdown_image": f'![Personalized Training Plan]({pub_url})',
    }


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

a2ui_instruction = schema_manager.generate_system_prompt(
    role_description="Workout Enabler, an encouraging personal workout coach and recovery assistant.",
    workflow_description="Analyze the user request and return structured A2UI display cards for workout plans, exercise guides, metrics, and recovery summaries.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

SYSTEM_INSTRUCTION = a2ui_instruction + "\n\n" + """
Physical Limitations & Memory Directive:
You MUST always remember, prioritize, and strictly enforce any physical limitations, injuries, joint constraints, or health conditions that the user mentions or has stored in Memory Bank (e.g., lower back pain, knee arthritis, shoulder impingement, asthma, wrist pain).
Whenever formulating ANY workout routine, exercise guide, training split, or fitness recommendation:
1. Check for remembered or stated physical limitations.
2. Explicitly tailor all exercise selections, intensity levels, and safety guidance to accommodate those limitations.
3. Warn the user about high-risk movements for their specific condition and provide safe, gentle alternatives.
"""

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=SYSTEM_INSTRUCTION,
    code_executor=get_code_executor(),
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
    tools=[
        PreloadMemoryTool(),
        generate_personalized_training_plan,
        list_workout_routines,
        get_exercise_guide,
        search_public_exercise_db,
        generate_workout_image,
        generate_exercise_demo_video,
        generate_exercise_visual,
        log_workout,
        get_workout_history,
        save_user_profile,
        check_inactivity_status,
        calculate_fitness_metrics,
        schedule_inactivity_reminder,
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
