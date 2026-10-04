# Traceability: acceptance criterion → test → source

Maps each IS-1 (User Authorisation and Authentication) acceptance criterion
or story clarification to the test that proves it and the file that
implements it. Created in Phase 4; covers Phase 3 (authentication), Phase 4
(authorisation policy), and Phase 5 (consolidation) together, since all are
IS-1. Audited against every criterion in Phase 5 — see the "Route-level and
plumbing" and "Closed during the Phase 5 audit" sections below for what that
audit actually found and fixed, rather than just asserting coverage.

## Phase 3 — authentication, session context, idle timeout

| Criterion / source | Test | Implementation |
|---|---|---|
| JWT verified locally against this project's real signing-key system (ES256/JWKS, confirmed against the live project, not assumed) | `test_auth_jwt.py::test_valid_token_verifies_and_returns_claims` | `app/auth/jwt.py` |
| Each rejection reason (missing/malformed header, unknown kid, bad signature, expired, wrong issuer/audience, missing `session_id`) produces a distinct, stable code | `test_auth_jwt.py::test_rejection_cases_produce_specific_codes[*]`, `::test_bad_signature_is_rejected` | `app/auth/jwt.py::verify_token` |
| Key rotation must not cause a window of wrongly-rejected tokens | `test_auth_jwt.py::test_unknown_kid_triggers_exactly_one_refetch` | `app/auth/jwt.py::_JWKSCache` |
| A valid token produces the correct `CurrentUser` (id/email/name/roles/session_id) | `test_auth_context.py::test_valid_token_produces_expected_current_user` | `app/auth/context.py::register_auth_hooks` |
| Multi-role user gets every role, at the auth layer | `test_auth_context.py::test_multi_role_user_gets_both_roles_in_frozenset` | `app/auth/context.py::_load_profile_with_roles` |
| "Given a user session, when it's been idle beyond a defined timeout, the user is logged out and must re-authenticate" | `test_auth_context.py::test_idle_session_rejected_with_auth_session_idle` | `app/auth/context.py::_check_and_update_session_activity` (design: `docs/design-decisions.md` §idle timeout) |
| A rejected (idle) request must not refresh its own clock | same test, asserts `touch_calls == []` | `app/auth/context.py::_check_and_update_session_activity` |
| Idle-activity writes shouldn't happen on every request | `test_auth_context.py::test_debounce_two_rapid_requests_produce_one_write` | `app/auth/context.py` (`_ACTIVITY_DEBOUNCE_SECONDS`) |
| Routes are protected by default; `@public` is the only opt-out | `test_auth_context.py::test_public_route_works_with_no_token`, `::test_protected_route_rejects_without_token` | `app/auth/context.py::register_auth_hooks`, `::public` |
| `_get_last_active` / `_touch_session_activity` behave correctly against the REAL `session_activity` table (caught a real `.maybe_single()` null-handling bug unit tests structurally couldn't) | `test_session_activity_integration.py::test_get_last_active_returns_none_for_unknown_session`, `::test_touch_then_get_round_trips`, `::test_touch_twice_upserts_rather_than_duplicating` | `app/auth/context.py` |
| `_load_profile_with_roles`'s real nested-relationship query (`user_roles(role)`) against the real `profiles`/`user_roles` tables — found completely untested (not even by a unit test, since unit tests always monkeypatch this function) during the Phase 5 audit | `test_session_activity_integration.py::test_load_profile_with_roles_against_real_seeded_coordinator` | `app/auth/context.py::_load_profile_with_roles` |
| `verify_token`'s real HTTP fetch against the project's actual JWKS endpoint, with a real signed-in user's token — also found untested as a whole (only the verification *logic* was tested, against a synthetic JWKS) during the Phase 5 audit. This test is also what found a real, intermittent production bug (clock-skew leeway; see `docs/design-decisions.md`) that no unit test could have surfaced. | `test_jwt_integration.py::test_verify_token_against_real_jwks_and_a_real_signed_in_user` | `app/auth/jwt.py::verify_token`, `::_http_get_json` |
| Clock-skew tolerance on `iat` (the fix the above integration test drove) | `test_auth_jwt.py::test_small_clock_skew_on_iat_is_tolerated`, `::test_large_clock_skew_on_iat_is_still_rejected` | `app/auth/jwt.py` (`_CLOCK_SKEW_LEEWAY_SECONDS`) |

## Phase 4 — authorisation policy

| Criterion / source | Test | Implementation |
|---|---|---|
| "An organiser sees full details of their own events; other organisers' events are hidden" (ruled: 404, not a partial view) | `test_authz_policy.py::test_organiser_denied_on_another_organisers_event`, `::test_organiser_allowed_on_own_event` | `app/authz/rules.py::rule_event_view` |
| Prerequisite: an assigned coordinator can view the event they're assigned to | `test_authz_policy.py::test_coordinator_allowed_view_on_assigned_event` | `app/authz/rules.py::rule_event_view` |
| "An organiser cannot edit directly after submission; changes go via the coordinator" | `test_authz_policy.py::test_organiser_denied_edit_after_submission`, `::test_organiser_allowed_edit_while_draft`, `::test_organiser_edit_behaviour_unchanged_by_coordinator_window` | `app/authz/rules.py::rule_event_edit` |
| Event Information Management story: coordinator updates event information during planning (closes the gap where no rule permitted ANY coordinator edit); IS-31: once submitted, only the coordinator can edit, so also during `under_review` | `test_authz_policy.py::test_coordinator_allowed_edit_assigned_event_under_review_or_planning`, `::test_coordinator_denied_edit_assigned_event_outside_review_and_planning`, `test_event_submission.py::test_is31_assigned_coordinator_can_edit_the_request`, `::test_coordinator_denied_edit_on_event_assigned_to_someone_else`, `::test_multi_role_union_on_same_event_for_edit` | `app/authz/rules.py::rule_event_edit` |
| "A coordinator acts only on events assigned to them" (approve) + Event Status Management workflow | `test_authz_policy.py::test_coordinator_denied_approve_on_event_assigned_to_someone_else`, `::test_coordinator_denied_approve_from_status_other_than_under_review`, `::test_coordinator_allowed_approve_on_own_assigned_event_under_review` | `app/authz/rules.py::rule_event_approve` |
| Same, for reject | `test_authz_policy.py::test_coordinator_denied_reject_on_event_assigned_to_someone_else`, `::test_coordinator_denied_reject_from_status_other_than_under_review`, `::test_coordinator_allowed_reject_on_own_assigned_event_under_review` | `app/authz/rules.py::rule_event_reject` |
| Event Review and Approval story: "Request Clarification", coordinator-only, status stays `under_review` | `test_authz_policy.py::test_coordinator_allowed_request_clarification_under_review`, `::test_coordinator_denied_request_clarification_on_unassigned_event`, `::test_coordinator_denied_request_clarification_from_status_other_than_under_review` | `app/authz/rules.py::rule_event_request_clarification` |
| Cancelled Status story: "Coordinator can change status to cancelled after approval of the event request" | `test_authz_policy.py::test_coordinator_denied_cancel_before_approval`, `::test_coordinator_allowed_cancel_post_approval_on_own_event`, `::test_coordinator_denied_cancel_on_event_assigned_to_someone_else` | `app/authz/rules.py::rule_event_cancel` (status set is a decision, not an inference — see `docs/design-decisions.md` §event.cancel; confirmation requested in `docs/open-questions.md`) |
| "A user's access is limited to their role" — only an Event Organizer creates an event request | `test_authz_policy.py::test_attendee_denied_event_create_role_only_no_resource`, `::test_organiser_allowed_event_create` | `app/authz/rules.py::rule_event_create` |
| View Event Requests story: organiser can list their own drafted/created requests | `test_authz_policy.py::test_event_list_denied_for_role_with_no_listing_rights`, `::test_organiser_allowed_event_list` | `app/authz/rules.py::rule_event_list` |
| View Assigned Event Requests story: coordinator can list events assigned to them | `test_authz_policy.py::test_coordinator_allowed_event_list` | `app/authz/rules.py::rule_event_list` (caller MUST apply the scoping filter — see the loud warning in the module docstring) |
| Event Status Management story: submitting changes status to Submitted, organiser-only, from draft, or from rejected to resubmit after corrections | `test_authz_policy.py::test_organiser_denied_event_submit_on_event_that_isnt_theirs`, `::test_organiser_denied_event_submit_from_status_other_than_draft_or_rejected`, `::test_organiser_allowed_event_submit_from_draft`, `::test_organiser_allowed_event_resubmit_after_rejection`, `test_event_submission.py::test_resubmit_returns_every_rejected_session_to_its_coordinator` | `app/authz/rules.py::rule_event_submit` |
| Readied for Justin's `coordinator_service.py::reassign_coordinator` (not wired by this ticket). Sprint 2: now refused once `completed` — see the Sprint 2 section | `test_authz_policy.py::test_coordinator_allowed_reassign_when_currently_assigned`, `::test_coordinator_denied_reassign_when_not_currently_assigned` | `app/authz/rules.py::rule_event_reassign_coordinator` |
| "An attendee cannot [do] internal actions" | `test_authz_policy.py::test_attendee_denied_every_internal_action` | all `rule_event_*` functions (deny via role/relationship check) |
| Customer requirement: a user with multiple roles gets the union of their permissions | `test_authz_policy.py::test_multi_role_user_gets_union_of_permissions` | `app/authz/rules.py` (structural: `role in user.roles`, never a single-role assumption) |
| Deny by default: an unknown action string is never allowed | `test_authz_policy.py::test_unknown_action_denied` | `app/authz/policy.py::_decide` |
| Deny by default: a real action with no rule wired up is never allowed | `test_authz_policy.py::test_registered_action_with_no_rule_denied` | `app/authz/policy.py::_decide` |
| 403-vs-404 selection: relationship exists but a condition blocks the action → 403 | `test_authz_policy.py::test_403_not_404_when_relationship_exists_but_status_blocks` | `app/authz/policy.py::authorise`, `docs/design-decisions.md` §403 vs 404 |
| 403-vs-404 selection: no relationship at all → 404 | `test_authz_policy.py::test_404_not_403_when_no_relationship_exists` | same |

## Route-level and plumbing (found untested during the Phase 5 audit)

These aren't acceptance criteria in themselves, but they're the concrete
interface the ticket promised to other developers ("four other developers
depend on it") and had literally zero tests until this audit.

| What | Test | Implementation |
|---|---|---|
| `GET /me` returns id/email/name/roles for the authenticated caller | `test_me_route.py::test_me_returns_id_email_name_roles_for_authenticated_user` | `app/me/routes.py` |
| `GET /me` needs no policy check — works for any role, including attendee | `test_me_route.py::test_me_works_for_any_role_no_policy_check` | `app/me/routes.py` |
| `GET /me` is protected by default like every other route | `test_me_route.py::test_me_rejects_without_token` | `app/auth/context.py::register_auth_hooks` |
| `@require(action, loader=...)` authorises and passes the loaded resource to the view, exactly as the docstring's usage example claims | `test_authz_decorators.py::test_require_with_loader_authorises_and_passes_resource_to_view` | `app/authz/decorators.py::require` |
| `@require` denies per the policy, loader result included | `test_authz_decorators.py::test_require_with_loader_denies_when_policy_says_no` | same |
| A loader's own `NotFoundError` propagates unmodified — same 404 a failed existence-sensitive authorisation would produce | `test_authz_decorators.py::test_require_loaders_own_not_found_propagates_unchanged` | same |
| `@require(action)` with no loader is role-only, no resource passed to the view | `test_authz_decorators.py::test_require_without_loader_is_role_only`, `::test_require_without_loader_denies_wrong_role` | same |
| `@require` never runs the loader for an unauthenticated caller | `test_authz_decorators.py::test_require_rejects_unauthenticated_before_loader_runs` | same |
| `current_user()` raises rather than returning `None` if misused on a route where no user was attached | `test_auth_context.py::test_current_user_raises_if_called_on_a_public_route` | `app/auth/context.py::current_user` |

## Justin's coordinator-assignment coverage (converted in Phase 5, not IS-1's own criteria)

Not IS-1 acceptance criteria — Justin's Coordinator Assignment story. Converted
from his original print-and-eyeball scripts (`backend/test_assignment.py`,
`backend/test_reassignment.py`, both now deleted) into independent,
self-seeding pytest tests, per the Phase 5 instruction. Listed here for
completeness, not audited for full coverage of his story — only his original
scripts' coverage was preserved, not extended beyond it except for the audit
gaps below.

| What (from Justin's original scripts) | Test |
|---|---|
| A coordinator already booked on the target date is skipped | `test_coordinator_assignment_integration.py::test_assign_initial_coordinator_skips_coordinator_occupied_on_same_date` |
| Workload-based selection prefers a less-loaded coordinator | `::test_assign_initial_coordinator_prefers_less_loaded_coordinator` |
| Reassignment moves `coordinator_id` and writes an audit log entry | `::test_reassign_coordinator_records_audit_log` |
| Reassignment rejects a request from someone other than the current coordinator | `::test_reassign_coordinator_rejects_request_from_non_current_coordinator` |

Both assignment tests assert a *comparative* property (the occupied/busier
coordinator is never picked) rather than naming an exact winner — the real,
shared project has Phase 3's seeded coordinators (Alice, Brandon, Chloe) in
the same candidate pool, so asserting an exact winner would make the test
depend on seed data it doesn't own. One scenario from my own first draft —
"raises `NoCoordinatorAvailableError` when every coordinator is occupied" —
was written, found to be untestable against a shared database with other
coordinators genuinely free, and deliberately dropped rather than kept as a
flaky or environment-dependent test. It was never part of Justin's original
coverage either, so nothing of his was lost.

## Sprint 2 — status transitions (mechanism, IS-36, IS-38, IS-39)

Unit tests: `test_transitions.py` (state machine, no DB) and `test_event_lifecycle.py` (rules + routes, no DB).
Integration tests: `test_transitions_integration.py` (real Postgres; only what a unit test can't prove).

| Criterion / source | Test | Implementation |
|---|---|---|
| Every status change follows a sourced edge; nothing else is legal | `test_transitions.py::test_edge_set_is_exactly_the_sourced_edges`, `::test_every_legal_edge_is_allowed`, `::test_representative_illegal_edges_are_refused` | `app/events/transitions.py::ALLOWED` / `_EDGE_SOURCES` |
| A status change is atomic: two concurrent changes from the same status, exactly one wins | `test_transitions_integration.py::test_concurrent_transitions_from_same_status_exactly_one_wins`, `::test_many_identical_concurrent_transitions_exactly_one_wins` | `transitions.py::_db_conditional_update` (status in the WHERE clause) |
| A lost race is reported, never silently absorbed | `test_transitions.py::test_zero_rows_matched_is_a_conflict_not_a_silent_success`, `test_event_lifecycle.py::test_lost_race_between_authz_and_write_is_409` | `transitions.py::TransitionConflictError` (409) |
| Regression: a transition cannot write back a stale status (the old under_review write's bug) | `test_transitions.py::test_transition_cannot_write_back_a_stale_status`, `::test_conditional_update_filters_on_expected_status`, `test_transitions_integration.py::test_stale_expected_status_is_refused_against_real_postgres` | `transitions.py::transition` / `_db_conditional_update` |
| Every successful transition leaves one history row with from/to/actor/reason | `test_transitions.py::test_every_legal_edge_is_allowed`, `test_transitions_integration.py::test_history_row_records_from_to_actor_and_reason` | `transitions.py::_db_insert_history` → `event_status_log` |
| IS-36: "Coordinator can set planning only if current status is approved" | `test_event_lifecycle.py::test_is36_coordinator_can_set_planning_only_if_approved`, `::test_is36_start_planning_refused_unless_approved`, `::test_lifecycle_route_moves_event_and_records_actor[start-planning…]` | `rules.py::rule_event_start_planning`, `routes.py::start_planning`, edge `(approved, planning)` |
| "Coordinator can set confirmed only from planning" (status only; field-locking NOT built) | `test_event_lifecycle.py::test_step_refused_from_any_other_status[event.confirm…]`, `::test_lifecycle_route_moves_event_and_records_actor[confirm…]` | `rules.py::rule_event_confirm`, `routes.py::confirm_event`, edge `(planning, confirmed)` |
| IS-38: "Coordinator can set completed only from confirmed" | `test_event_lifecycle.py::test_is38_complete_refused_unless_confirmed`, `::test_lifecycle_route_moves_event_and_records_actor[complete…]` | `rules.py::rule_event_complete`, `routes.py::complete_event`, edge `(confirmed, completed)` |
| IS-38: "completed events are read-only going forward" | `test_event_lifecycle.py::test_completed_event_refuses_edit_submit_cancel_and_reassign`, `::test_is38_reassign_route_refused_on_completed_event`, `test_transitions.py::test_completed_event_cannot_move_anywhere` | every `rule_event_*` status window excludes `completed`; `rule_event_reassign_coordinator` precondition (added); no edge out of `completed` in `ALLOWED` |
| IS-39: Coordinator can cancel after approval | `test_event_lifecycle.py::test_is39_coordinator_can_cancel_after_approval`, `::test_is39_cancel_refused_before_approval_or_when_finished` | `rules.py::rule_event_cancel`, edges `(approved|planning|confirmed, cancelled)` |
| IS-39: cancellation requires a reason | `test_transitions.py::test_cancel_without_a_reason_is_refused`, `test_event_lifecycle.py::test_is39_cancel_without_a_reason_is_400_and_changes_nothing` | `transitions.py::REASON_REQUIRED` / `_clean_reason` |
| Approved/Rejected story: rejection requires a reason | `test_transitions.py::test_reject_without_a_reason_is_refused` | `transitions.py::REASON_REQUIRED` |
| IS-39: the reason is stored and the organiser can see it | `test_event_lifecycle.py::test_is39_cancel_stores_reason_and_returns_it`, `::test_is39_organiser_sees_cancellation_reason_in_status_history`, `::test_status_history_hidden_from_unrelated_organiser` | `routes.py::cancel_event`, `routes.py::get_status_history` (gated by `event.view`) |
| No status write bypasses the guarded path (the four former raw writes: creation, submit, auto-assignment, approve/reject) | `test_event_submit_transitions.py` (6 tests + rule params), `test_coordinator_assignment_status.py` (7), `test_event_decisions.py` (Justin's, retargeted), plus the grep recorded in the PR | `event_service.py::create_event_request` / `create_draft_request` (→ `record_creation`), `::submit_event_request`, `::_decide`; `coordinator_service.py::assign_initial_coordinator` |
| Regression: auto-assignment no longer writes back a status it read earlier | `test_coordinator_assignment_status.py::test_concurrent_status_change_is_not_reverted`, `::test_claim_never_writes_status` | `coordinator_service.py::assign_initial_coordinator` |
| "A rejected request can be re-submitted for review after the Organizer makes changes" | `test_event_submit_transitions.py::test_resubmission_keeps_same_coordinator_and_returns_to_review`, `::test_organiser_may_resubmit_a_rejected_request` | `rules.py::rule_event_submit` (draft or rejected), `event_service.py::submit_event_request` (existing-coordinator branch), edge `(rejected, submitted)` |
| Every lifecycle step, including creation and submission, leaves one audit row | `test_event_submit_transitions.py::test_first_submission_goes_draft_submitted_and_waits_for_the_lead`, `test_transitions.py::test_record_creation_writes_a_null_from_status_row` | `transitions.py::record_creation`, `::transition` |
| Error messages shown to users contain no raw status values | `test_transitions.py::test_no_transition_error_message_contains_a_raw_status_value` | `transitions.py::label` / `_REASON_MESSAGES` |

Not covered, because the feature doesn't exist: IS-39's "Organizer is
notified of cancellation and reason" (no notification system); IS-36's
"status gates venue/equipment search" (no venue-request-for-event route, no
equipment); the Confirmed Status story's field-locking. All are tracked in
`docs/open-questions.md`.

## Week 7 change #5 — Event Coordinator Lead

Unit tests: `test_coordinator_lead.py` (rules, routes, the Lead's list), `test_coordinator_assignment.py` (Lead-chosen assignment), `frontend/src/lib/leadDashboard.test.js` (dashboard grouping).

| Criterion (Week 7 Customer Changes, #5) | Test | Implementation |
|---|---|---|
| "Newly submitted event requests should no longer be assigned directly to an Event Coordinator" — they enter an unassigned queue | `test_event_submission.py::test_submit_from_one_session_submits_every_draft_session`, `::test_create_event_request_inserts_and_submits_every_session`, `test_event_submit_transitions.py::test_first_submission_goes_draft_submitted_and_waits_for_the_lead` | `event_service.py::_submit_sessions` (no assignment call); queue = `submitted` with no coordinator |
| "...that can be viewed by the Event Coordinator Lead" / "view all coordinator assignments and active events" | `test_coordinator_lead.py::test_lead_can_view_every_submitted_event_whoever_it_is_assigned_to`, `::test_lead_list_is_every_non_draft_event_plus_their_own_drafts`, `::test_lead_cannot_see_someone_elses_draft` | `rules.py::rule_event_view` / `rule_event_list` (`_is_lead_over`), `event_service.py::list_event_requests`, `LeadDashboard.vue` |
| "The Lead can ... assign a suitable Event Coordinator" | `test_coordinator_lead.py::test_lead_may_assign_a_request_in_the_unassigned_queue`, `::test_assign_route_assigns_the_leads_choice`, `::test_nobody_but_the_lead_may_assign`, `test_coordinator_assignment.py::test_lead_chosen_coordinator_gets_every_session_attributed_to_the_lead`, `::test_lead_chosen_coordinator_busy_on_any_session_is_refused` | `rules.py::rule_event_assign_coordinator`, `routes.py::assign_coordinator_route`, `coordinator_service.py::assign_initial_coordinator(coordinator_id=...)` |
| "...and reassign events where necessary" | `test_coordinator_lead.py::test_lead_may_reassign_any_assigned_event_but_not_once_completed`, `::test_reassign_route_lets_the_lead_override_the_current_coordinator_check` | `rules.py::rule_event_reassign_coordinator`, `routes.py::reassign_coordinator_route` |
| "Event Coordinators should only be able to manage events assigned to them" | `test_coordinator_lead.py::test_coordinator_still_only_sees_their_own_events` | unchanged coordinator rules |

Not covered, because not built: "Relevant users should be notified when
assignments or reassignments occur" (no notification system — see
`docs/open-questions.md`).

## Explicitly deferred (not tested because not built)

- Registration-related criteria ("an attendee cannot view another attendee's
  registration") — no `registrations` table or attendee-event linkage
  exists in the schema yet. No action, no rule, no test.
- Field-level visibility ("an attendee sees no internal planning
  information") — a serialisation concern, not a `can()` decision; deferred
  to whoever builds the event routes/serialisers. See
  `docs/design-decisions.md`.
