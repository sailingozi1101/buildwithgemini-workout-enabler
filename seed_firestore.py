"""Seed Firestore collection with initial workout routines for Workout Enabler."""

import subprocess
import google.auth
import google.oauth2.credentials
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-02-ff4db1ff689a"

ROUTINES = [
    {
        "routine_id": "routine-push-day",
        "title": "Upper Body Push Focus",
        "target_muscle": "Chest, Shoulders, Triceps",
        "difficulty": "Intermediate",
        "duration_minutes": 45,
        "exercises": [
            "Bench Press (3x10)",
            "Overhead Shoulder Press (3x12)",
            "Tricep Dips (3x15)",
            "Push-ups (3xMax)",
        ],
        "rest_interval_seconds": 60,
    },
    {
        "routine_id": "routine-leg-core",
        "title": "Legs & Core Power Workout",
        "target_muscle": "Quads, Hamstrings, Abs",
        "difficulty": "Beginner",
        "duration_minutes": 30,
        "exercises": [
            "Goblet Squats (4x12)",
            "Romanian Deadlifts (3x10)",
            "Plank (3x60s)",
            "Walking Lunges (3x12)",
        ],
        "rest_interval_seconds": 90,
    },
    {
        "routine_id": "routine-full-body-hiit",
        "title": "Full Body Conditioning HIIT",
        "target_muscle": "Full Body",
        "difficulty": "Advanced",
        "duration_minutes": 25,
        "exercises": [
            "Burpees (4x15)",
            "Kettlebell Swings (4x20)",
            "Mountain Climbers (4x45s)",
            "Jumping Jacks (4x60s)",
        ],
        "rest_interval_seconds": 30,
    },
]


def seed():
    print(f"Connecting to Firestore with hardcoded project ID: {PROJECT_ID}")
    try:
        token = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()
        creds = google.oauth2.credentials.Credentials(token)
        db = firestore.Client(project=PROJECT_ID, credentials=creds)
    except Exception as e:
        print(f"gcloud token failed ({e}), falling back to default auth...")
        db = firestore.Client(project=PROJECT_ID)

    collection_ref = db.collection("workout_routines")

    for routine in ROUTINES:
        doc_ref = collection_ref.document(routine["routine_id"])
        doc_ref.set(routine)
        print(f"Seeded document: {routine['routine_id']} -> {routine['title']}")

    print("Firestore seeding complete!")


if __name__ == "__main__":
    seed()
