import uuid
from django.test import TestCase, Client
from django.utils import timezone
from datetime import timedelta

from apps.assessments.models import (
    QuestionBank,
    AssessmentConfig,
    Candidate,
    AssessmentAttempt,
    AttemptQuestionSnapshot,
    IntegrityEvent,
)
from apps.assessments.services import (
    start_assessment_for_candidate,
    save_candidate_answer,
    finalize_assessment_attempt,
)


class AssessmentEngineTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.config = AssessmentConfig.objects.create(
            title="CSL Initial Assessment",
            duration_minutes=60,
            total_marks=50,
            aptitude_count=25,
            coding_count=25,
            max_attempts=1,
            is_active=True,
        )
        # Create 30 Aptitude and 30 Coding questions
        apt_list = []
        for i in range(30):
            apt_list.append(
                QuestionBank(
                    prompt=f"Aptitude Question {i+1}",
                    section_type=QuestionBank.SectionType.APTITUDE,
                    category="Quantitative",
                    difficulty="MEDIUM",
                    option_a="A",
                    option_b="B",
                    option_c="C",
                    option_d="D",
                    correct_option="A",
                    is_active=True,
                )
            )
        QuestionBank.objects.bulk_create(apt_list)

        cod_list = []
        for i in range(30):
            cod_list.append(
                QuestionBank(
                    prompt=f"Coding Question {i+1}",
                    section_type=QuestionBank.SectionType.CODING,
                    category="Python",
                    difficulty="MEDIUM",
                    option_a="A",
                    option_b="B",
                    option_c="C",
                    option_d="D",
                    correct_option="B",
                    is_active=True,
                )
            )
        QuestionBank.objects.bulk_create(cod_list)

    def test_candidate_registration_and_validation(self):
        payload = {
            "full_name": "Rathinam Student",
            "register_number": "721721U101",
            "college": "Rathinam College of Arts and Science",
            "email": "student01@rathinam.in",
            "department": "B.Sc Computer Science",
            "year_of_study": "Final Year",
            "phone_number": "9876543210",
        }
        res = self.client.post("/api/assessment/register/", payload, content_type="application/json")
        self.assertEqual(res.status_code, 201)
        self.assertIn("candidate_id", res.data)
        self.assertEqual(res.data["full_name"], "Rathinam Student")

        # Duplicate register number for same college should fail
        clash_payload = payload.copy()
        clash_payload["email"] = "different@example.com"
        res2 = self.client.post("/api/assessment/register/", clash_payload, content_type="application/json")
        self.assertEqual(res2.status_code, 400)

    def test_balanced_random_question_snapshot_and_answer_security(self):
        candidate = Candidate.objects.create(
            full_name="Karthik R",
            register_number="CSL-2026-01",
            college="CIT Coimbatore",
            email="karthik@example.com",
            department="CSE",
            year_of_study="3rd Year",
        )
        # Start assessment
        res = self.client.post("/api/assessment/start/", {"candidate_id": str(candidate.id)}, content_type="application/json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["state"], AssessmentAttempt.State.IN_PROGRESS)
        self.assertEqual(res.data["total_questions"], 50)
        self.assertEqual(len(res.data["questions"]), 50)

        attempt_id = res.data["id"]
        # Verify first 25 are Aptitude, next 25 are Coding
        first_q = res.data["questions"][0]
        self.assertEqual(first_q["section_type"], "APTITUDE")
        self.assertEqual(first_q["question_order"], 1)

        twenty_sixth_q = res.data["questions"][25]
        self.assertEqual(twenty_sixth_q["section_type"], "CODING")
        self.assertEqual(twenty_sixth_q["question_order"], 26)

        # SECURITY CHECK: correct_option must NEVER be exposed in student API
        for q in res.data["questions"]:
            self.assertNotIn("correct_option", q)
            self.assertNotIn("correct_option_key", q)

        # Autosave answer for Q1
        save_res = self.client.post(
            f"/api/assessment/attempts/{attempt_id}/answer/",
            {"question_order": 1, "selected_option": "A"},
            content_type="application/json",
        )
        self.assertEqual(save_res.status_code, 200)
        self.assertEqual(save_res.data["selected_option"], "A")

        # Record Integrity Event (e.g. Tab Hidden)
        event_res = self.client.post(
            f"/api/assessment/attempts/{attempt_id}/integrity-event/",
            {"event_type": "TAB_HIDDEN", "client_timestamp": timezone.now().isoformat()},
            content_type="application/json",
        )
        self.assertEqual(event_res.status_code, 200)
        self.assertEqual(event_res.data["tab_switches"], 1)

        # Finalize Attempt
        fin_res = self.client.post(f"/api/assessment/attempts/{attempt_id}/finalize/")
        self.assertEqual(fin_res.status_code, 200)
        self.assertEqual(fin_res.data["state"], AssessmentAttempt.State.SUBMITTED)
        self.assertIn("total_score", fin_res.data)
        self.assertIn("percentage", fin_res.data)

        # Retrieve Result API
        res_view = self.client.get(f"/api/assessment/attempts/{attempt_id}/result/")
        self.assertEqual(res_view.status_code, 200)
        self.assertEqual(res_view.data["candidate_name"], "Karthik R")
        self.assertEqual(res_view.data["total_score"], fin_res.data["total_score"])
