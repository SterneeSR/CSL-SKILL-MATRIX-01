import random
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from rest_framework.exceptions import ValidationError

from .models import (
    QuestionBank,
    AssessmentConfig,
    Candidate,
    AssessmentAttempt,
    AttemptQuestionSnapshot,
    IntegrityEvent,
)


def get_or_create_default_config():
    config = AssessmentConfig.objects.filter(is_active=True).first()
    if not config:
        config = AssessmentConfig.objects.create(
            title="CSL Initial Assessment",
            description="50-mark balanced aptitude and coding fundamentals assessment.",
            duration_minutes=60,
            total_marks=50,
            aptitude_count=25,
            coding_count=25,
            max_attempts=1,
            max_tab_switches_warning=3,
            auto_submit_on_tab_limit=False,
            is_active=True,
        )
    return config


def validate_question_bank_sufficiency(config=None):
    if not config:
        config = get_or_create_default_config()

    active_aptitude = QuestionBank.objects.filter(
        section_type=QuestionBank.SectionType.APTITUDE, is_active=True
    ).count()
    active_coding = QuestionBank.objects.filter(
        section_type=QuestionBank.SectionType.CODING, is_active=True
    ).count()

    errors = []
    if active_aptitude < config.aptitude_count:
        errors.append(
            f"Insufficient aptitude questions in bank: found {active_aptitude}, requires {config.aptitude_count}."
        )
    if active_coding < config.coding_count:
        errors.append(
            f"Insufficient coding questions in bank: found {active_coding}, requires {config.coding_count}."
        )

    if errors:
        raise ValidationError({"bank_error": " ".join(errors)})
    return True


@transaction.atomic
def start_assessment_for_candidate(candidate: Candidate, config: AssessmentConfig = None):
    """
    Starts an assessment attempt for the candidate with balanced question selection and snapshotting.
    """
    if not config:
        config = get_or_create_default_config()

    # Check attempt limit
    completed_attempts = AssessmentAttempt.objects.filter(
        candidate=candidate,
        state__in=[
            AssessmentAttempt.State.SUBMITTED,
            AssessmentAttempt.State.TIMED_OUT,
            AssessmentAttempt.State.FLAGGED_FOR_REVIEW,
        ],
    ).count()
    if completed_attempts >= config.max_attempts:
        raise ValidationError({"detail": "Maximum attempts reached for this assessment."})

    # Check if there is already an active attempt in progress
    existing_in_progress = AssessmentAttempt.objects.filter(
        candidate=candidate,
        state__in=[AssessmentAttempt.State.CREATED, AssessmentAttempt.State.IN_PROGRESS],
    ).first()

    if existing_in_progress:
        # Check if expired
        if existing_in_progress.is_expired():
            finalize_assessment_attempt(existing_in_progress, final_state=AssessmentAttempt.State.TIMED_OUT)
            raise ValidationError({"detail": "Your previous assessment attempt has expired."})
        return existing_in_progress

    # Validate bank sufficiency
    validate_question_bank_sufficiency(config)

    # 1. Balanced Question Selection
    # Select 25 Aptitude
    aptitude_qs = list(
        QuestionBank.objects.filter(
            section_type=QuestionBank.SectionType.APTITUDE, is_active=True
        )
    )
    # Balanced by difficulty if available, else random sample
    selected_aptitude = random.sample(aptitude_qs, config.aptitude_count)

    # Select 25 Coding
    coding_qs = list(
        QuestionBank.objects.filter(
            section_type=QuestionBank.SectionType.CODING, is_active=True
        )
    )
    selected_coding = random.sample(coding_qs, config.coding_count)

    now = timezone.now()
    deadline = now + timedelta(minutes=config.duration_minutes)

    # 2. Create Attempt
    attempt = AssessmentAttempt.objects.create(
        candidate=candidate,
        config=config,
        state=AssessmentAttempt.State.IN_PROGRESS,
        started_at=now,
        deadline=deadline,
    )

    # 3. Create Snapshots with option shuffling
    # We sequence: 1-25 Aptitude, 26-50 Coding
    all_selected = [(q, i + 1) for i, q in enumerate(selected_aptitude)] + [
        (q, i + 26) for i, q in enumerate(selected_coding)
    ]

    snapshots = []
    for q, order in all_selected:
        # Original options mapping
        orig_options = [
            ("A", q.option_a),
            ("B", q.option_b),
            ("C", q.option_c),
            ("D", q.option_d),
        ]
        # Shuffle options
        shuffled = orig_options.copy()
        random.shuffle(shuffled)

        # Map which shuffled key (A, B, C, D) points to original correct key
        keys = ["A", "B", "C", "D"]
        correct_key_in_shuffled = "A"
        for idx, (orig_key, text) in enumerate(shuffled):
            if orig_key == q.correct_option:
                correct_key_in_shuffled = keys[idx]

        snapshots.append(
            AttemptQuestionSnapshot(
                attempt=attempt,
                question=q,
                question_order=order,
                section_type=q.section_type,
                prompt=q.prompt,
                option_a_text=shuffled[0][1],
                option_b_text=shuffled[1][1],
                option_c_text=shuffled[2][1],
                option_d_text=shuffled[3][1],
                correct_option_key=correct_key_in_shuffled,
            )
        )

    AttemptQuestionSnapshot.objects.bulk_create(snapshots)

    # Record started event
    IntegrityEvent.objects.create(
        attempt=attempt,
        event_type=IntegrityEvent.EventType.ATTEMPT_STARTED,
        metadata={"started_at": now.isoformat()},
    )

    return attempt


@transaction.atomic
def save_candidate_answer(attempt: AssessmentAttempt, question_order: int, selected_option: str):
    """
    Idempotent single answer save. Validates deadline and attempt state.
    """
    if attempt.state != AssessmentAttempt.State.IN_PROGRESS:
        raise ValidationError({"detail": f"Attempt is not active (state: {attempt.state})."})

    if attempt.is_expired():
        finalize_assessment_attempt(attempt, final_state=AssessmentAttempt.State.TIMED_OUT)
        raise ValidationError({"detail": "Assessment time has expired."})

    snapshot = attempt.question_snapshots.filter(question_order=question_order).first()
    if not snapshot:
        raise ValidationError({"detail": "Invalid question order."})

    selected_clean = selected_option.strip().upper() if selected_option else ""
    if selected_clean and selected_clean not in ("A", "B", "C", "D"):
        raise ValidationError({"detail": "Invalid option selected."})

    snapshot.selected_option = selected_clean
    snapshot.answered_at = timezone.now()
    snapshot.save(update_fields=["selected_option", "answered_at", "updated_at"])

    return snapshot


@transaction.atomic
def finalize_assessment_attempt(attempt: AssessmentAttempt, final_state=AssessmentAttempt.State.SUBMITTED):
    """
    Evaluates MCQs server-side, tallies scores, locks answers, transitions state.
    """
    # If already finalized, return current attempt
    if attempt.state in [
        AssessmentAttempt.State.SUBMITTED,
        AssessmentAttempt.State.TIMED_OUT,
        AssessmentAttempt.State.FLAGGED_FOR_REVIEW,
    ]:
        return attempt

    now = timezone.now()
    snapshots = attempt.question_snapshots.select_related("question").all()

    aptitude_score = 0
    coding_score = 0

    for s in snapshots:
        if s.selected_option and s.selected_option == s.correct_option_key:
            s.is_correct = True
            if s.section_type == QuestionBank.SectionType.APTITUDE:
                aptitude_score += 1
            else:
                coding_score += 1
        else:
            s.is_correct = False
        s.save(update_fields=["is_correct", "updated_at"])

    total_score = aptitude_score + coding_score
    percentage = round((total_score / 50.0) * 100.0, 2)

    attempt.state = final_state
    attempt.aptitude_score = aptitude_score
    attempt.coding_score = coding_score
    attempt.total_score = total_score
    attempt.percentage = percentage
    attempt.submitted_at = now
    attempt.save(
        update_fields=[
            "state",
            "aptitude_score",
            "coding_score",
            "total_score",
            "percentage",
            "submitted_at",
            "updated_at",
        ]
    )

    IntegrityEvent.objects.create(
        attempt=attempt,
        event_type=IntegrityEvent.EventType.SUBMITTED if final_state == AssessmentAttempt.State.SUBMITTED else IntegrityEvent.EventType.TIMED_OUT,
        metadata={"total_score": total_score, "final_state": final_state},
    )

    return attempt
