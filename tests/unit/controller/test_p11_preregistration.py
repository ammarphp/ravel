"""C34 uses the actual approved-plan preregistration producer and refusal gates."""
from test_research_launch import (
    test_checkin1_approval_writes_code_derived_preregistration as test_C34_checkin1_plan_produces_trusted_preregistration,
    test_cli_command_refuses_unapproved_plan as test_C34_unapproved_plan_cannot_preregister,
    test_hand_written_preregistration_cannot_launch as test_C34_hand_written_preregistration_cannot_launch,
    test_preregistration_must_match_current_derivation as test_C34_preregistration_must_match_current_approved_derivation,
)
