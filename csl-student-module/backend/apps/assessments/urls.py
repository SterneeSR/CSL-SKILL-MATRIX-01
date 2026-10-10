from django.urls import path
from .views import (
    CandidateRegisterView,
    StartAssessmentView,
    AttemptStateView,
    SaveAnswerView,
    RecordIntegrityEventView,
    FinalizeAssessmentView,
    AssessmentResultView,
)

urlpatterns = [
    path("register/", CandidateRegisterView.as_view(), name="assessment-register"),
    path("start/", StartAssessmentView.as_view(), name="assessment-start"),
    path("attempts/<uuid:attempt_id>/", AttemptStateView.as_view(), name="assessment-attempt-state"),
    path("attempts/<uuid:attempt_id>/answer/", SaveAnswerView.as_view(), name="assessment-save-answer"),
    path("attempts/<uuid:attempt_id>/integrity-event/", RecordIntegrityEventView.as_view(), name="assessment-integrity-event"),
    path("attempts/<uuid:attempt_id>/finalize/", FinalizeAssessmentView.as_view(), name="assessment-finalize"),
    path("attempts/<uuid:attempt_id>/result/", AssessmentResultView.as_view(), name="assessment-result"),
]
