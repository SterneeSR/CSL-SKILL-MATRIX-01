import uuid
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError


class QuestionBank(models.Model):
    class SectionType(models.TextChoices):
        APTITUDE = "APTITUDE", "Aptitude"
        CODING = "CODING", "Coding Fundamentals"

    class Difficulty(models.TextChoices):
        EASY = "EASY", "Easy"
        MEDIUM = "MEDIUM", "Medium"
        HARD = "HARD", "Hard"

    prompt = models.TextField(help_text="MCQ question text or problem statement")
    section_type = models.CharField(max_length=20, choices=SectionType.choices, db_index=True)
    category = models.CharField(max_length=100, db_index=True, help_text="e.g. Quantitative, Logical, Python, OOP")
    difficulty = models.CharField(max_length=20, choices=Difficulty.choices, default=Difficulty.MEDIUM, db_index=True)
    
    # MCQ Options
    option_a = models.TextField()
    option_b = models.TextField()
    option_c = models.TextField()
    option_d = models.TextField()
    
    # Correct Answer (Never exposed to student APIs)
    correct_option = models.CharField(
        max_length=1,
        choices=[("A", "Option A"), ("B", "Option B"), ("C", "Option C"), ("D", "Option D")],
        help_text="The single correct option key (A, B, C, or D)",
    )
    explanation = models.TextField(blank=True, default="", help_text="Optional explanation for admin review")
    
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["section_type", "category", "id"]
        indexes = [
            models.Index(fields=["section_type", "is_active"]),
            models.Index(fields=["section_type", "difficulty", "is_active"]),
        ]

    def __str__(self):
        return f"[{self.section_type}] {self.category} ({self.difficulty}): {self.prompt[:60]}"


class AssessmentConfig(models.Model):
    title = models.CharField(max_length=200, default="CSL Initial Assessment")
    description = models.TextField(blank=True, default="CSL 50-mark balanced diagnostic assessment.")
    duration_minutes = models.PositiveIntegerField(default=60, help_text="Duration in minutes (e.g. 60)")
    total_marks = models.PositiveIntegerField(default=50)
    aptitude_count = models.PositiveIntegerField(default=25, help_text="Required aptitude questions")
    coding_count = models.PositiveIntegerField(default=25, help_text="Required coding questions")
    max_attempts = models.PositiveIntegerField(default=1, help_text="Default 1 attempt per student")
    
    # Integrity monitoring thresholds
    max_tab_switches_warning = models.PositiveIntegerField(default=3)
    auto_submit_on_tab_limit = models.BooleanField(default=False)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Assessment Configuration"
        verbose_name_plural = "Assessment Configurations"

    def __str__(self):
        return f"{self.title} ({self.duration_minutes} mins, {self.total_marks} marks)"


class Candidate(models.Model):
    """
    Candidate registered specifically for the initial assessment.
    Can be passwordless during initial assessment, later linked or activated to a full User account.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=150)
    register_number = models.CharField(max_length=100)
    college = models.CharField(max_length=200, help_text="College / Institution name")
    email = models.EmailField(db_index=True)
    department = models.CharField(max_length=150, help_text="Department / Course")
    year_of_study = models.CharField(max_length=50, help_text="e.g. 1st Year, 2nd Year, Final Year")
    phone_number = models.CharField(max_length=30, blank=True, default="")
    
    # Optional link to formal User account (once activated/approved)
    user = models.OneToOneField(
        "users.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assessment_candidate",
    )
    
    # Expiring single-use activation token for later account claim
    activation_token = models.CharField(max_length=100, blank=True, default="", db_index=True)
    activation_token_expires_at = models.DateTimeField(null=True, blank=True)
    is_email_verified = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # College-scoped uniqueness for register_number, plus global uniqueness for normalized email
            models.UniqueConstraint(fields=["college", "register_number"], name="uniq_candidate_college_regno"),
            models.UniqueConstraint(fields=["email"], name="uniq_candidate_email"),
        ]

    def clean(self):
        self.email = self.email.strip().lower()
        self.register_number = self.register_number.strip().upper()
        self.college = self.college.strip()

    def __str__(self):
        return f"{self.full_name} ({self.register_number} - {self.college})"


class AssessmentAttempt(models.Model):
    class State(models.TextChoices):
        CREATED = "CREATED", "Created"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        SUBMITTED = "SUBMITTED", "Submitted"
        TIMED_OUT = "TIMED_OUT", "Timed Out"
        FLAGGED_FOR_REVIEW = "FLAGGED_FOR_REVIEW", "Flagged for Review"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="attempts")
    config = models.ForeignKey(AssessmentConfig, on_delete=models.PROTECT, related_name="attempts")
    
    state = models.CharField(max_length=30, choices=State.choices, default=State.CREATED, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    deadline = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    
    # Computed marks (Backend authoritative)
    aptitude_score = models.IntegerField(default=0)
    coding_score = models.IntegerField(default=0)
    total_score = models.IntegerField(default=0)
    percentage = models.FloatField(default=0.0)
    
    # Integrity flags
    tab_switch_count = models.PositiveIntegerField(default=0)
    fullscreen_exit_count = models.PositiveIntegerField(default=0)
    is_flagged = models.BooleanField(default=False)
    flag_reason = models.TextField(blank=True, default="")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["candidate", "state"]),
            models.Index(fields=["state", "deadline"]),
        ]

    def __str__(self):
        return f"{self.candidate.full_name} - {self.state} ({self.total_score}/50)"

    def is_expired(self):
        if self.deadline and timezone.now() > self.deadline:
            return True
        return False


class AttemptQuestionSnapshot(models.Model):
    """
    Immutable snapshot of the exact 50 questions selected for a candidate attempt,
    including the stable randomized option ordering for that attempt.
    """
    attempt = models.ForeignKey(AssessmentAttempt, on_delete=models.CASCADE, related_name="question_snapshots")
    question = models.ForeignKey(QuestionBank, on_delete=models.PROTECT, related_name="attempt_snapshots")
    question_order = models.PositiveIntegerField(help_text="1 to 50 ordering in attempt")
    section_type = models.CharField(max_length=20, choices=QuestionBank.SectionType.choices)
    
    # Captured prompt and shuffled options mapping for student rendering
    prompt = models.TextField()
    option_a_text = models.TextField()
    option_b_text = models.TextField()
    option_c_text = models.TextField()
    option_d_text = models.TextField()
    
    # The actual original key that maps to the correct option for this shuffled display
    correct_option_key = models.CharField(max_length=1, help_text="A, B, C, or D for this snapshot display")
    
    # Student's answer
    selected_option = models.CharField(max_length=1, blank=True, default="", help_text="A, B, C, or D")
    is_correct = models.BooleanField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["attempt", "question_order"]
        constraints = [
            models.UniqueConstraint(fields=["attempt", "question_order"], name="uniq_attempt_question_order"),
            models.UniqueConstraint(fields=["attempt", "question"], name="uniq_attempt_question_dup"),
        ]

    def __str__(self):
        return f"Attempt {self.attempt_id} - Q{self.question_order} ({self.section_type})"


class IntegrityEvent(models.Model):
    class EventType(models.TextChoices):
        ATTEMPT_STARTED = "ATTEMPT_STARTED", "Attempt Started"
        FULLSCREEN_ENTER = "FULLSCREEN_ENTER", "Full-screen Entered"
        FULLSCREEN_EXIT = "FULLSCREEN_EXIT", "Full-screen Exited"
        TAB_HIDDEN = "TAB_HIDDEN", "Tab Switched / Hidden"
        TAB_VISIBLE = "TAB_VISIBLE", "Tab Restored / Visible"
        RECONNECTED = "RECONNECTED", "Connection Restored"
        SUBMITTED = "SUBMITTED", "Submitted"
        TIMED_OUT = "TIMED_OUT", "Timed Out"

    attempt = models.ForeignKey(AssessmentAttempt, on_delete=models.CASCADE, related_name="integrity_events")
    event_type = models.CharField(max_length=40, choices=EventType.choices)
    client_timestamp = models.DateTimeField(null=True, blank=True)
    server_timestamp = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(blank=True, default=dict)

    class Meta:
        ordering = ["-server_timestamp"]
        indexes = [
            models.Index(fields=["attempt", "event_type"]),
        ]

    def __str__(self):
        return f"{self.attempt_id} - {self.event_type} at {self.server_timestamp}"
