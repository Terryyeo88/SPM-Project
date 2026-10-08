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
| Event Information Management story: coordinator updates event information during planning (closes the gap where no rule permitted ANY coordinator edit); IS-31: once submitted, only the coordinator can edit, so also during `under_review` | `test_authz_policy.py::test_coordinator_allowed_edit_assigned_event_whenever_it_is_still_live`, `::test_coordinator_denied_edit_once_the_event_is_finished` (IS-21: widened to every status but completed/cancelled), `test_event_submission.py::test_is31_assigned_coordinator_can_edit_the_request`, `::test_coordinator_denied_edit_on_event_assigned_to_someone_else`, `::test_multi_role_union_on_same_event_for_edit` | `app/authz/rules.py::rule_event_edit` |
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

## Venue Booking Request / Approval (Josiah, Sprint 2)

Not IS-1's own criteria — the Venue Booking Request (3pt) and Venue Booking
Approval (5pt) stories. Design reasoning for every inference below (role
scoping, the `approved → planning` side effect, the narrow conflict guard)
lives in `docs/design-decisions.md` §Venue Booking Request / Approval;
customer-confirmation items are flagged in `docs/open-questions.md`.

| Criterion / source | Test | Implementation |
|---|---|---|
| Coordinator submits a booking (venue + the event session's own date/time/requirements); status set to "Pending" | `test_booking_service.py::test_create_booking_applies_setup_and_turnaround_buffers` | `app/venues/booking_service.py::create_booking_request` |
| Only the event's ASSIGNED coordinator may request a booking | `test_authz_venue_bookings.py::test_assigned_coordinator_can_create_when_event_approved`, `::test_coordinator_not_assigned_gets_404_not_403`, `::test_organiser_cannot_create_even_on_their_own_event`, `::test_venue_staff_cannot_create` | `app/authz/rules.py::rule_venue_booking_create` |
| Incomplete requests blocked (no `venue_id`, or one that doesn't reference a real venue) | `test_booking_service.py::test_create_booking_requires_a_venue_id`, `::test_create_booking_raises_for_unknown_venue` | `app/venues/booking_service.py::create_booking_request` |
| Linked to the event record for traceability | `test_booking_service.py::test_list_bookings_for_event_newest_first` | `venue_bookings.event_id` (FK), `app/venues/booking_service.py::list_bookings_for_event` |
| System automatically applies a configurable setup time (before) and turnaround time (after) to the booked period | `test_booking_service.py::test_create_booking_applies_setup_and_turnaround_buffers` | `app/venues/booking_service.py::_event_window`, `create_booking_request` |
| Buffer values are per-venue, and don't retroactively change once a booking already exists | `test_booking_service.py::test_create_booking_snapshots_buffers_not_a_live_reference` | `venue_bookings.setup_minutes`/`turnaround_minutes` (snapshotted columns) |
| Booking visible to relevant Venue Staff (queue) | `test_booking_service.py::test_list_bookings_is_unfiltered_for_venue_staff`, `::test_list_bookings_for_a_user_with_both_roles_is_unfiltered` | `app/venues/booking_service.py::list_bookings` |
| Venue Staff see a queue of ALL pending requests (role-only — no per-venue-staff-assignment table; see `docs/open-questions.md`) | `test_authz_venue_bookings.py::test_venue_staff_allowed_venue_booking_list`, `test_booking_service.py::test_list_bookings_status_filter_narrows_within_role_scope` | `app/authz/rules.py::rule_venue_booking_list`, `app/venues/booking_service.py::list_bookings` |
| Venue Staff approve → "Confirmed", venue marked unavailable for that period | `test_booking_service.py::test_confirm_booking_sets_status_and_logs_the_decision`, `::test_confirm_booking_not_blocked_by_a_non_overlapping_confirmed_booking` | `app/venues/booking_service.py::confirm_booking` |
| Approval is blocked if another CONFIRMED booking already overlaps the same venue's padded period (narrow guard — not full Conflict Detection, see `docs/design-decisions.md`) | `test_booking_service.py::test_confirm_booking_blocked_by_an_overlapping_confirmed_booking`, `test_venue_bookings_integration.py::test_get_booking_reports_conflict_against_a_real_overlapping_confirmed_booking` | `app/venues/booking_service.py::_confirmed_overlap_exists`, `confirm_booking` |
| The same conflict is surfaced read-only BEFORE a decision is made (suitability panel) | `test_booking_service.py::test_get_booking_conflict_is_true_when_another_confirmed_booking_overlaps`, `::test_get_booking_conflict_excludes_itself` | `app/venues/booking_service.py::get_booking` (`conflict` field) |
| Venue Staff reject, must provide a reason | `test_booking_service.py::test_reject_booking_requires_a_reason_and_leaves_status_unchanged`, `::test_reject_booking_rejects_every_blank_or_non_string_reason` | `app/venues/booking_service.py::reject_booking` |
| Coordinator can view the rejection reason | `test_booking_service.py::test_get_booking_attaches_the_latest_rejection_reason`, `::test_get_booking_rejection_is_the_most_recent_one`, `test_venue_bookings_integration.py::test_reject_booking_records_reason_coordinator_can_then_read` | `app/venues/booking_service.py::_attach_rejection_reasons`, `app/authz/rules.py::rule_venue_booking_view` (requester OR any venue_staff) |
| Only `venue_staff` may approve/reject, and only while the booking is still `pending` (race-proofed against a double decision) | `test_authz_venue_bookings.py::test_venue_staff_cannot_redecide_an_already_decided_booking`, `::test_requesting_coordinator_cannot_decide_their_own_booking`, `test_booking_service.py::test_second_decision_is_refused_once_no_longer_pending` | `app/authz/rules.py::rule_venue_booking_approve`/`rule_venue_booking_reject`, `app/venues/booking_service.py::_decide_booking` |
| An approved booking should notify the Coordinator (ties to the unbuilt Notification System — print-stub only, no real plumbing exists anywhere in this codebase yet) | not independently tested — see `app/venues/booking_service.py::_notify_booking_decision`'s own docstring | `app/venues/booking_service.py::_notify_booking_decision` |
| Routes wire the above up with the correct authz per role (POST/GET on the events blueprint, 4 routes on the venues blueprint, static `/bookings` paths before the dynamic `/<venue_id>`) | `test_venue_bookings_routes.py` (all cases) | `app/events/routes.py::create_venue_booking`, `get_venue_bookings_for_event`; `app/venues/routes.py::list_venue_bookings_route`, `get_venue_booking_route`, `approve_venue_booking_route`, `reject_venue_booking_route` |
| End-to-end against a real database (migration actually applies, buffers/conflict/rejection round-trip for real) | `test_venue_bookings_integration.py` (all cases) | `supabase/migrations/20261005100000_venue_bookings.sql`, `app/venues/booking_service.py` |
| Frontend: tab grouping, request-form validation | `frontend/src/lib/venueBookings.test.js` | `frontend/src/lib/venueBookings.js` |
| Frontend: capacity/layout/accessibility suitability comparison | `frontend/src/lib/venueSuitability.test.js` | `frontend/src/lib/venueSuitability.js` |
| Frontend: the 3 new routes are correctly role-gated (including static-before-dynamic ordering) | `frontend/src/router/index.test.js` (the 3 new `describe` blocks + the `/venues/bookings` swallow-guard) | `frontend/src/router/index.js`, `frontend/src/lib/roles.js` |

Not independently covered by an automated test (manual/visual only, no
browser tooling available in this environment — see the PR description):
`RequestVenueBookingView.vue`, `VenueBookingQueueView.vue`,
`VenueBookingReviewView.vue`, `VenueBookingStatus.vue` — consistent with
this project's existing "no component tests, pure logic only" convention
(see `frontend/src/lib/coordinatorDashboard.test.js` and its sibling
components, none of which have component tests either).

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

## Attendee Registration (Justin)

Unit tests: `test_registrations.py` (rules, validation, service, routes), `frontend/src/lib/registrations.test.js`. Integration: `test_registrations_integration.py` (local stack). The database function was also exercised directly against Postgres 16, including 20 concurrent registrations.

| Acceptance criterion | Test | Implementation |
|---|---|---|
| Register only for an event that is confirmed and enabled for registration | `test_registrations.py::test_attendee_cannot_register_unless_confirmed_and_enabled`, `::test_register_route_hides_an_unconfirmed_session_from_attendees`, `test_registrations_integration.py::test_the_database_refuses_a_session_that_is_not_confirmed` | `rules.py::rule_event_register`; `register_attendee` (`not_open`) |
| Register only during the permitted registration period | `test_registrations.py::test_register_explains_each_refusal`, `test_registrations_integration.py::test_registration_only_during_the_window` | `register_attendee` (`not_started` / `closed`, database clock) |
| The Attendee can provide the required registration information | `test_registrations.py::test_email_is_required_valid_and_normalised`, `::test_phone_is_required`, `::test_phone_must_look_like_a_phone_number`, `::test_at_least_one_notification_channel_is_required`, `::test_name_and_organisation_cannot_be_submitted`, `::test_included_organisation_is_the_profiles`, `::test_notes_are_optional_trimmed_and_capped`, `registrations.test.js` (prefill) | `registration_service.validate_registration_details`; `RegistrationForm.vue` |
| Capacity available → registration recorded as confirmed | `test_registrations.py::test_register_returns_the_recorded_registration[confirmed]`, `test_registrations_integration.py::test_capacity_fills_then_waitlists_first_come_first_served` | `register_attendee` (capacity = `expected_attendance`) |
| Capacity reached and waiting list available → recorded as waitlisted | `test_registrations.py::test_register_returns_the_recorded_registration[waitlisted]`, `::test_my_registrations_show_waiting_list_position_first_come_first_served`, `test_registrations_integration.py::test_capacity_fills_then_waitlists_first_come_first_served` | `register_attendee`; `registration_service.list_my_registrations` (position) |
| Only attendees register and see registrations | `test_registrations.py::test_only_attendees_register`, `::test_only_attendees_browse_and_list_their_registrations`, `::test_list_routes_are_attendee_only` | `rules.py::rule_event_register` / `rule_registration_list` |

| Withdraw / leave the waiting list (attendee wireframe; Week 4 "register, view status, withdraw") | `test_registrations.py::test_withdraw_reports_whether_the_next_person_moved_up`, `::test_withdraw_without_a_registration_is_404`, `::test_withdraw_after_the_session_started_is_refused`, `::test_only_attendees_withdraw`, `test_registrations_integration.py::test_withdrawing_a_confirmed_place_moves_the_first_waitlisted_attendee_up` | `withdraw_registration` (promotes the first waitlisted); `AttendeeEventView.vue` |

Not covered, because not built: notifications (see `docs/open-questions.md`).

## Explicitly deferred (not tested because not built)

- "An attendee cannot view another attendee's registration" — there is no
  route that returns anyone else's registration (`/registrations/mine` is
  scoped to the caller), so there is nothing to deny yet.
- Field-level visibility ("an attendee sees no internal planning
  information") — a serialisation concern, not a `can()` decision; deferred
  to whoever builds the event routes/serialisers. See
  `docs/design-decisions.md`.

## Booking conflicts (IS-16, Terry, Sprint 2)

IS-16's acceptance criteria aren't recorded in this repo. The rows below
trace the criteria as the team agreed them; check them against the
ticket. Design reasoning: `docs/design-decisions.md` §Booking conflicts
(IS-16).

| Criterion | Test | Implementation |
|---|---|---|
| Two confirmed bookings of one venue cannot hold overlapping periods, even when confirmed concurrently | `test_booking_conflicts_integration.py::test_constraint_refuses_concurrent_confirms_of_overlapping_bookings` (negative control: constraint dropped, both land; restored, exactly one) | `20261006000000_venue_booking_no_overlap.sql` (exclusion constraint) |
| The blocked period runs from setup start to turnaround end, so turnaround between events is enforced | `test_booking_conflicts_integration.py::test_report_and_constraint_agree_at_the_boundaries` (the constraint compares the padded columns) | Constraint on `booking_start`/`booking_end`, which IS-14 pads with setup/turnaround |
| Back-to-back bookings (one ends when the next starts) are not a conflict | `test_booking_conflicts.py::test_bookings_that_only_touch_do_not_clash`, `test_booking_conflicts_integration.py::test_report_and_constraint_agree_at_the_boundaries` | `'[)'` range in the constraint; `_spans_overlap` in the report |
| Venue Staff see WHICH existing booking(s) a request clashes with | `test_booking_conflicts.py::test_returns_every_clashing_booking_not_just_the_first`, `::test_each_clash_says_which_event_holds_the_venue`, `::test_venue_staff_see_which_bookings_clash` | `app/venues/booking_conflicts.py`, `GET /venues/bookings/<id>/conflicts` (`app/venues/conflict_routes.py`) |
| A booking is never reported as clashing with itself | `test_booking_conflicts.py::test_a_booking_never_clashes_with_itself`, `::test_clashes_for_booking_uses_the_bookings_own_venue_and_period` | `confirmed_clashes(exclude_booking_id=...)` |
| Only people who may view the booking see its clashes | `test_booking_conflicts.py::test_requesting_coordinator_may_see_the_clashes`, `::test_other_coordinators_get_404`, `::test_missing_booking_is_404` | `@require(VENUE_BOOKING_VIEW)` |
| Rejected (or later cancelled) bookings stop blocking the period | `test_booking_conflicts_integration.py::test_releasing_a_confirmed_booking_frees_its_period`, `test_booking_conflicts.py::test_query_reads_only_the_statuses_the_constraint_covers` | Constraint `WHERE (status = 'confirmed')`; `_BLOCKING_STATUSES` |
| Report and constraint agree on what "overlap" means | `test_booking_conflicts_integration.py::test_report_and_constraint_agree_at_the_boundaries` (4 boundary cases) | Same `'[)'` semantics in both |

Not covered, because not built: showing the clash list in the Venue Staff
UI (the frontend is Josiah's, and `VenueBookingReviewView.vue` doesn't call
the new route yet); releasing a confirmed booking when its event is
cancelled (no booking cancellation path exists).

## Request for Event Change (IS-21, Sprint 2)

Unit tests: `test_event_change_requests.py` (rules, service, routes), `frontend/src/lib/changeRequests.test.js`, `frontend/src/components/EventChangeRequests.test.js`. Integration: `test_event_change_requests_integration.py` (local stack). Design reasoning: `docs/design-decisions.md` §Request for Event Change (IS-21).

| Acceptance criterion | Test | Implementation |
|---|---|---|
| The Event Organiser can request permitted changes for an event that has been submitted | `test_event_change_requests.py::test_organiser_may_request_a_change_once_submitted[*]`, `::test_request_change_refused_outside_the_submitted_window[*]`, `::test_request_change_hidden_from_another_organiser`, `::test_coordinator_cannot_request_a_change_on_the_organisers_behalf`, `::test_create_route_records_a_change_for_the_organiser`, `::test_create_route_refuses_a_draft`, `::test_ac1_a_change_can_be_requested_at_every_stage_after_submission[*]`, `::test_ac1_no_change_request_outside_the_submitted_window[*]` | `rules.py::rule_event_request_change` (`CHANGE_REQUEST_STATUSES`), `routes.py::create_change_request` |
| The Event Organiser can specify the event detail(s) they want to change | `::test_request_records_only_the_details_that_change`, `::test_several_details_can_be_changed_in_one_request`, `::test_turning_registration_off_records_the_cleared_window_too`, `::test_invalid_change_requests_are_refused_and_nothing_is_recorded[*]` (incl. `status`, `coordinator_id`, `organizer_id`, `shared_event_id`, `id` refused), `::test_a_change_to_nothing_new_is_refused`, `changeRequests.test.js` (`buildChanges`), `EventChangeRequests.test.js` (organiser) | `change_request_service.py::request_event_change` (validated with `validate_event_payload`, same rules as an edit); `EventChangeRequests.vue` |
| A submitted change request is recorded for the relevant event | `::test_request_is_recorded_against_the_request_and_the_session`, `::test_legacy_event_without_shared_event_id_is_a_group_of_one`, `::test_create_route_records_a_change_for_the_organiser` (tied to `event_id` + `shared_event_id`, readable back by the organiser), `::test_list_for_a_legacy_event_reads_only_its_own_requests`, `::test_only_one_change_request_waits_for_review_per_session`, `test_event_change_requests_integration.py::test_change_request_round_trips_and_approval_writes_the_event`, `::test_database_allows_only_one_pending_change_per_session` | `20261008000000_event_change_requests_and_logs.sql` (`event_change_requests`: `shared_event_id` + `event_id`, one pending per session) |
| The assigned Event Coordinator can view and review the requested change | `::test_assigned_coordinator_may_review_a_change[*]`, `::test_only_the_assigned_coordinator_reviews`, `::test_review_refused_once_the_event_has_moved_on[*]`, `::test_assigned_coordinator_lists_the_change_requests` (what, before/after, who, why), `::test_ac4_the_assigned_coordinator_reviews_through_the_routes`, `::test_ac4_a_request_waiting_for_a_coordinator_is_reviewable_by_nobody_yet`, `::test_list_hides_changes_on_sessions_the_caller_cannot_see`, `::test_approving_writes_the_change_to_the_session`, `::test_approving_a_shared_detail_renames_every_session_of_the_request`, `::test_rejecting_keeps_the_event_as_it_was_and_records_the_reason`, `::test_rejecting_needs_a_reason[*]`, `::test_a_change_is_reviewed_once[*]`, `::test_a_decision_that_loses_the_race_writes_nothing`, `::test_approval_is_revalidated_against_the_event_as_it_is_now`, `EventChangeRequests.test.js` (coordinator) | `rules.py::rule_event_review_change`, `change_request_service.py::list_change_requests` / `approve_change_request` / `reject_change_request`, `routes.py` change-request routes |
| Given that an event is confirmed, the Event Organiser cannot directly overwrite the current confirmed event details | `::test_organiser_cannot_edit_a_confirmed_event_directly`, `::test_requesting_a_change_does_not_touch_the_event`, `::test_confirmed_event_changes_only_after_coordinator_approval` (route-level, end to end), `::test_ac5_the_organiser_cannot_save_over_a_confirmed_event_either_way`, `::test_ac5_a_pending_change_does_not_show_on_the_confirmed_event`, `::test_organiser_cannot_approve_their_own_change` | `rules.py::rule_event_edit` (unchanged: organiser draft/rejected only); requested values live in `event_change_requests` until `approve_change_request` writes them |

Each criterion was also checked by breaking it in the code (draft made requestable, any field changeable, request not tied to its session, any coordinator may review, approval not applied, requesting writes the event, organiser may edit a confirmed event) -- every break failed at least one of the tests above. `change_request_service.py`, `event_log.py` and `change_impact.py` are at 100% line coverage.

Not covered, because not built: notifying the coordinator of a new change
request or the organiser of the decision (no notification system), and a
"pending changes" count on the coordinator dashboard. See
`docs/open-questions.md`.

### IS-21 follow-up: impact on arrangements already made (team request, 8 Oct)

"Alert the coordinator before a significant change is committed, presenting which already-made arrangements it touches (venue, equipment, technical support, registration)."

| Criterion | Test | Implementation |
|---|---|---|
| Venue: a change that no longer fits the booked period, capacity, layout or accessibility is flagged | `test_event_change_requests.py::test_moving_the_session_outside_its_venue_booking_is_flagged`, `::test_a_timing_change_that_still_fits_the_booking_is_not_flagged`, `::test_a_pending_booking_counts_but_a_rejected_one_does_not`, `::test_venue_requirement_changes_are_checked_against_the_booked_venue` | `app/events/change_impact.py::_venue_impacts` |
| Registration: registered attendees affected by timing, capacity or turning registration off | `::test_registered_attendees_are_flagged_when_the_timing_or_capacity_changes`, `::test_turning_registration_off_with_attendees_registered_is_flagged`, `::test_no_registrations_means_no_registration_impact` | `change_impact.py::_registration_impacts` |
| Equipment / technical support: flagged for a manual check (no records exist to check against) | `::test_equipment_and_technical_support_ask_for_a_manual_check`, `::test_a_session_without_equipment_needs_no_equipment_check` | `change_impact.py::_untracked_impacts` |
| Only real arrangements count (nothing before approval; unrelated fields) | `::test_nothing_is_arranged_before_approval`, `::test_details_no_arrangement_depends_on_have_no_impact` | `change_impact.py::assess_change_impact` (`ARRANGED_STATUSES`) |
| The coordinator sees the impacts before deciding | `::test_pending_changes_are_listed_with_their_impact`, `EventChangeRequests.test.js` (impact describe block) | `change_request_service.py::list_change_requests`, `EventChangeRequests.vue` |
| Nothing is committed until every affected area is acknowledged, including one that appeared after the page loaded; what was acknowledged is recorded | `::test_approval_waits_until_every_affected_area_is_acknowledged`, `::test_an_impact_that_appears_after_the_page_loaded_must_be_acknowledged_too`, `::test_a_change_with_no_impact_is_approved_without_acknowledgement`, `::test_acknowledge_impacts_must_be_a_list_of_areas`, `::test_confirmed_event_changes_only_after_coordinator_approval` (409 then 200) | `change_request_service.py::_check_acknowledged` / `approve_change_request`, `event_change_requests.acknowledged_impacts` |

### IS-21 follow-up: event logs (what changed, who changed it, when)

Unit tests: `test_event_logs.py`, `frontend/src/components/EventLogHistory.test.js`. Integration: `test_event_change_requests_integration.py::test_change_request_round_trips_and_approval_writes_the_event`.

| Criterion | Test | Implementation |
|---|---|---|
| Each log entry records what changed (from -> to), who changed it and when, linked to the request's `shared_event_id` | `test_event_logs.py::test_entry_records_what_who_and_which_request`, `::test_diff_keeps_only_changed_fields_as_from_and_to`, `::test_diff_treats_the_same_instant_in_another_timezone_as_unchanged`, `::test_nothing_is_logged_when_nothing_changed`, `::test_a_legacy_event_is_logged_under_its_own_id` | `app/events/event_log.py::record_event_change`, `event_logs` table |
| Event logs and change requests are separate | `::test_requesting_a_change_is_logged_as_a_request_not_a_change`, `::test_a_rejected_change_request_adds_nothing_after_the_request`, `::test_an_approved_change_request_reads_requested_then_changed`, `::test_someone_who_is_both_organiser_and_coordinator_makes_changes`, `EventLogHistory.test.js` | `event_change_requests` (the requests) vs `event_logs` (timeline: requested / changed, `event_log.py::entry_kind`) |
| Every change to a submitted event is logged, whoever made it | `::test_a_shared_detail_is_written_to_every_session_but_logged_once`, `::test_coordinator_edit_is_logged`, `::test_organiser_fixing_a_rejected_session_is_logged`, `::test_draft_edits_are_not_logged`, `test_event_submission.py::test_is31_assigned_coordinator_can_edit_the_request` | `change_request_service.py::approve_change_request`, `routes.py::_log_direct_edit` |
| Anyone who may view the event can read its history | `::test_log_is_the_whole_request_newest_first`, `::test_log_includes_who_made_each_change`, `::test_log_is_hidden_from_unrelated_users`, `EventLogHistory.test.js` | `GET /events/<id>/logs`, `event_log.py::list_event_logs`, `EventLogHistory.vue` |
