from rest_framework import serializers
from .models import (
    Candidate,
    AssessmentAttempt,
    AttemptQuestionSnapshot,
    AssessmentConfig,
    IntegrityEvent,
)


class CandidateRegistrationSerializer(serializers.ModelSerializer):
    email = serializers.EmailField()

    class Meta:
        model = Candidate
        fields = [
            "id",
            "full_name",
            "register_number",
            "college",
            "email",
            "department",
            "year_of_study",
            "phone_number",
        ]

    def validate_email(self, value):
        return value.strip().lower()

    def validate_register_number(self, value):
        return value.strip().upper()

    def validate_college(self, value):
        return value.strip()


class QuestionSnapshotStudentSerializer(serializers.ModelSerializer):
    """
    Student-facing question serializer.
    STRICT SECURITY: correct_option_key is NEVER included.
    """
    options = serializers.SerializerMethodField()

    class Meta:
        model = AttemptQuestionSnapshot
        fields = [
            "question_order",
            "section_type",
            "prompt",
            "options",
            "selected_option",
        ]

    def get_options(self, obj):
        return [
            {"key": "A", "text": obj.option_a_text},
            {"key": "B", "text": obj.option_b_text},
            {"key": "C", "text": obj.option_c_text},
            {"key": "D", "text": obj.option_d_text},
        ]


class AssessmentAttemptDetailSerializer(serializers.ModelSerializer):
    questions = serializers.SerializerMethodField()
    remaining_seconds = serializers.SerializerMethodField()
    candidate_name = serializers.CharField(source="candidate.full_name", read_only=True)
    college = serializers.CharField(source="candidate.college", read_only=True)
    total_questions = serializers.SerializerMethodField()

    class Meta:
        model = AssessmentAttempt
        fields = [
            "id",
            "state",
            "started_at",
            "deadline",
            "remaining_seconds",
            "candidate_name",
            "college",
            "total_questions",
            "questions",
        ]

    def get_total_questions(self, obj):
        return 50

    def get_remaining_seconds(self, obj):
        if not obj.deadline:
            return 0
        from django.utils import timezone
        diff = (obj.deadline - timezone.now()).total_seconds()
        return max(0, int(diff))

    def get_questions(self, obj):
        snapshots = obj.question_snapshots.all().order_by("question_order")
        return QuestionSnapshotStudentSerializer(snapshots, many=True).data


class AnswerSaveSerializer(serializers.Serializer):
    question_order = serializers.IntegerField(min_value=1, max_value=50)
    selected_option = serializers.CharField(required=False, allow_blank=True)


class IntegrityEventSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(choices=IntegrityEvent.EventType.choices)
    client_timestamp = serializers.DateTimeField(required=False, allow_null=True)
    metadata = serializers.DictField(required=False, default=dict)


class AssessmentResultSerializer(serializers.ModelSerializer):
    candidate_name = serializers.CharField(source="candidate.full_name", read_only=True)
    register_number = serializers.CharField(source="candidate.register_number", read_only=True)
    college = serializers.CharField(source="candidate.college", read_only=True)
    department = serializers.CharField(source="candidate.department", read_only=True)

    class Meta:
        model = AssessmentAttempt
        fields = [
            "id",
            "candidate_name",
            "register_number",
            "college",
            "department",
            "state",
            "aptitude_score",
            "coding_score",
            "total_score",
            "percentage",
            "started_at",
            "submitted_at",
        ]
