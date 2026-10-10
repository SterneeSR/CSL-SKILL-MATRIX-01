from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import (
    Candidate,
    AssessmentAttempt,
    IntegrityEvent,
    AssessmentConfig,
)
from .serializers import (
    CandidateRegistrationSerializer,
    AssessmentAttemptDetailSerializer,
    AnswerSaveSerializer,
    IntegrityEventSerializer,
    AssessmentResultSerializer,
)
from .services import (
    start_assessment_for_candidate,
    save_candidate_answer,
    finalize_assessment_attempt,
    get_or_create_default_config,
)


class CandidateRegisterView(APIView):
    """
    Step 1: Student opens assessment portal, enters academic & identity details.
    Passwordless flow supported; checks college + reg_no and email constraints.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CandidateRegistrationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        email = data["email"]
        college = data["college"]
        reg_no = data["register_number"]

        # Check existing candidate by email or (college, reg_no)
        existing_candidate = Candidate.objects.filter(email=email).first()
        if existing_candidate:
            # If same candidate re-registering before attempting, update details
            for key, val in data.items():
                setattr(existing_candidate, key, val)
            existing_candidate.save()
            candidate = existing_candidate
        else:
            college_reg_clash = Candidate.objects.filter(college=college, register_number=reg_no).first()
            if college_reg_clash:
                return Response(
                    {"register_number": [f"Register number {reg_no} is already registered for {college}."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            candidate = serializer.save()

        # Check if already completed attempt
        completed = candidate.attempts.filter(
            state__in=[
                AssessmentAttempt.State.SUBMITTED,
                AssessmentAttempt.State.TIMED_OUT,
                AssessmentAttempt.State.FLAGGED_FOR_REVIEW,
            ]
        ).first()

        if completed:
            return Response(
                {
                    "candidate_id": str(candidate.id),
                    "already_completed": True,
                    "attempt_id": str(completed.id),
                    "message": "You have already completed the initial assessment.",
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "candidate_id": str(candidate.id),
                "full_name": candidate.full_name,
                "college": candidate.college,
                "already_completed": False,
            },
            status=status.HTTP_201_CREATED,
        )


class StartAssessmentView(APIView):
    """
    Step 2: Start or resume assessment attempt.
    Selects 25 Aptitude + 25 Coding MCQs with randomized snapshotting.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        candidate_id = request.data.get("candidate_id")
        if not candidate_id:
            return Response({"candidate_id": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)

        candidate = get_object_or_404(Candidate, id=candidate_id)
        config = get_or_create_default_config()

        attempt = start_assessment_for_candidate(candidate, config)
        serializer = AssessmentAttemptDetailSerializer(attempt)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AttemptStateView(APIView):
    """
    Step 3: Retrieve current active attempt (for reconnect / page refresh).
    """
    permission_classes = [AllowAny]

    def get(self, request, attempt_id):
        attempt = get_object_or_404(AssessmentAttempt, id=attempt_id)
        # Check timeout
        if attempt.state == AssessmentAttempt.State.IN_PROGRESS and attempt.is_expired():
            finalize_assessment_attempt(attempt, final_state=AssessmentAttempt.State.TIMED_OUT)

        serializer = AssessmentAttemptDetailSerializer(attempt)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SaveAnswerView(APIView):
    """
    Step 4: Save individual MCQ answer. Validates deadline server-side.
    """
    permission_classes = [AllowAny]

    def post(self, request, attempt_id):
        attempt = get_object_or_404(AssessmentAttempt, id=attempt_id)
        serializer = AnswerSaveSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        q_order = serializer.validated_data["question_order"]
        sel_opt = serializer.validated_data.get("selected_option", "")

        snapshot = save_candidate_answer(attempt, q_order, sel_opt)
        return Response(
            {
                "question_order": snapshot.question_order,
                "selected_option": snapshot.selected_option,
                "saved_at": snapshot.answered_at,
                "status": "saved",
            },
            status=status.HTTP_200_OK,
        )


class RecordIntegrityEventView(APIView):
    """
    Step 5: Record tab switch, full-screen toggle, reconnect integrity events.
    """
    permission_classes = [AllowAny]

    def post(self, request, attempt_id):
        attempt = get_object_or_404(AssessmentAttempt, id=attempt_id)
        serializer = IntegrityEventSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        ev_type = serializer.validated_data["event_type"]
        client_ts = serializer.validated_data.get("client_timestamp")
        metadata = serializer.validated_data.get("metadata", {})

        IntegrityEvent.objects.create(
            attempt=attempt,
            event_type=ev_type,
            client_timestamp=client_ts,
            metadata=metadata,
        )

        if ev_type in (IntegrityEvent.EventType.TAB_HIDDEN, IntegrityEvent.EventType.FULLSCREEN_EXIT):
            if ev_type == IntegrityEvent.EventType.TAB_HIDDEN:
                attempt.tab_switch_count += 1
            else:
                attempt.fullscreen_exit_count += 1

            # Auto-submit violation policy check
            if attempt.config.auto_submit_on_tab_limit and attempt.tab_switch_count >= attempt.config.max_tab_switches_warning:
                attempt.is_flagged = True
                attempt.flag_reason = f"Exceeded tab switch limit ({attempt.tab_switch_count})"
                finalize_assessment_attempt(attempt, final_state=AssessmentAttempt.State.FLAGGED_FOR_REVIEW)

            attempt.save(update_fields=["tab_switch_count", "fullscreen_exit_count", "is_flagged", "flag_reason", "updated_at"])

        return Response({"status": "recorded", "tab_switches": attempt.tab_switch_count}, status=status.HTTP_200_OK)


class FinalizeAssessmentView(APIView):
    """
    Step 6: Finalize assessment and calculate scores out of 50.
    """
    permission_classes = [AllowAny]

    def post(self, request, attempt_id):
        attempt = get_object_or_404(AssessmentAttempt, id=attempt_id)
        final_state = AssessmentAttempt.State.SUBMITTED
        if attempt.is_expired():
            final_state = AssessmentAttempt.State.TIMED_OUT

        finalized_attempt = finalize_assessment_attempt(attempt, final_state=final_state)
        serializer = AssessmentResultSerializer(finalized_attempt)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AssessmentResultView(APIView):
    """
    Step 7: View finalized result.
    """
    permission_classes = [AllowAny]

    def get(self, request, attempt_id):
        attempt = get_object_or_404(AssessmentAttempt, id=attempt_id)
        if attempt.state in [AssessmentAttempt.State.CREATED, AssessmentAttempt.State.IN_PROGRESS]:
            if attempt.is_expired():
                finalize_assessment_attempt(attempt, final_state=AssessmentAttempt.State.TIMED_OUT)
            else:
                return Response(
                    {"detail": "Assessment attempt is still in progress."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer = AssessmentResultSerializer(attempt)
        return Response(serializer.data, status=status.HTTP_200_OK)
