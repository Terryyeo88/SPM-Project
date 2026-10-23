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
| Readied for Justin's `coordinator_service.py::reassign_coordinator` (not wired by this ticket). Sprint 2: now refused once `completed` — see the Sprint 2 section. Sprint 3: Lead only — see "Reassignment is Lead-only" below | `test_authz_policy.py::test_coordinator_denied_reassign_even_when_currently_assigned`, `::test_coordinator_denied_reassign_when_not_currently_assigned` | `app/authz/rules.py::rule_event_reassign_coordinator` |
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
| Only the event's ASSIGNED coordinator may request a booking | `test_authz_venue_bookings.py::test_assigned_coordinator_can_create_when_event_planning`, `::test_assigned_coordinator_cannot_create_outside_planning[*]`, `::test_coordinator_not_assigned_gets_404_not_403`, `::test_organiser_cannot_create_even_on_their_own_event`, `::test_venue_staff_cannot_create` | `app/authz/rules.py::rule_venue_booking_create` |
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

## Sprint 2 — Check Equipment Availability (IS-18, Nawaz)

Unit tests: `test_equipment_service.py` (the availability arithmetic), `test_authz_equipment.py` (rules), `test_equipment_routes.py` (routes), `frontend/src/lib/equipment.test.js`, `frontend/src/views/equipment/EquipmentRequestDetailView.test.js`.

| Criterion (Equipment Availability Checking) | Test | Implementation |
|---|---|---|
| Can select an equipment request and view the required date and time | `test_equipment_routes.py::test_get_request_for_technical_staff`, `test_equipment_service.py::test_get_request_flattens_items_and_event_name`, `EquipmentRequestDetailView.test.js` ("shows the event, the required date and time...") | `equipment_service.py::get_request`, `routes.py::get_equipment_request_route`, `EquipmentRequestsView.vue` / `EquipmentRequestDetailView.vue` |
| Shows whether the requested quantity of each item is available for that date and time | `test_equipment_service.py::test_all_units_free_is_sufficient`, `::test_reservation_for_a_different_period_is_not_subtracted`, `::test_back_to_back_reservation_does_not_conflict`, `::test_timezones_are_compared_as_instants_not_wall_clock` | `equipment_service.py::check_availability` |
| Flags items where available is less than requested | `test_equipment_service.py::test_flags_only_the_short_item_not_the_whole_request`, `::test_type_with_no_units_is_flagged_not_an_error`, `equipment.test.js::describeAvailability`, `EquipmentRequestDetailView.test.js` ("flags the short item...") | `check_availability` (`sufficient`, `shortfall`), `lib/equipment.js::describeAvailability` |
| Subtracts equipment allocated to other confirmed requests for the same date and time | `test_equipment_service.py::test_overlapping_reservation_by_another_request_is_subtracted`, `::test_reservation_overlapping_by_one_minute_conflicts`, `::test_requests_own_reservations_are_excluded` | `check_availability` (reservation overlap, excluding the request's own) |
| Submitted equipment request is viewable later | `test_authz_equipment.py::test_coordinator_can_view_their_own_request`, `test_equipment_service.py::test_coordinator_lists_only_their_own_requests` | `equipment_requests` table, `get_request`, `list_requests`, `rule_equipment_request_view` |
| Equipment record shows when it is occupied, for which event, and the reservation period | `test_equipment_service.py::test_get_equipment_returns_occupancy_with_event_and_period`, `::test_get_equipment_only_exposes_event_id_and_name` | `equipment_service.py::get_equipment`, `EquipmentDetailView.vue` |
| Track equipment at unit level | `test_equipment_service.py::test_units_out_of_service_are_not_counted_available`, `::test_response_carries_request_period_and_event` | `equipment_units` table (one row per unit), `20261008000000_equipment.sql` |
| Only Technical Support Staff can run the check | `test_authz_equipment.py::test_requesting_coordinator_cannot_check_availability`, `::test_other_roles_denied_equipment_records`, `frontend/src/router/index.test.js` (equipment routes) | `rules.py::rule_equipment_request_check_availability`, `lib/roles.js` `ROUTE_ACCESS` |

Not covered, because the feature doesn't exist: recording an equipment request, accepting or rejecting one, updating a reserved quantity, and releasing equipment on cancellation (separate stories); the reservation exclusion constraint itself has no integration test (see `docs/open-questions.md`).

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
| A submitted change request is recorded for the relevant event | `::test_request_is_recorded_against_the_request_and_the_session`, `::test_legacy_event_without_shared_event_id_is_a_group_of_one`, `::test_create_route_records_a_change_for_the_organiser` (tied to `event_id` + `shared_event_id`, readable back by the organiser), `::test_list_for_a_legacy_event_reads_only_its_own_requests`, `::test_only_one_change_request_waits_for_review_per_session`, `test_event_change_requests_integration.py::test_change_request_round_trips_and_approval_writes_the_event`, `::test_database_allows_only_one_pending_change_per_session` | `20261009000000_event_change_requests_and_logs.sql` (`event_change_requests`: `shared_event_id` + `event_id`, one pending per session) |
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
| Equipment / technical support: flagged for a manual check when nothing has been requested through the system (equipment requests that exist are checked -- see IS-9 below) | `::test_equipment_and_technical_support_ask_for_a_manual_check`, `::test_a_session_without_equipment_needs_no_equipment_check` | `change_impact.py::_equipment_impacts`, `::_technical_support_impacts` |
| Only real arrangements count (nothing before approval; unrelated fields) | `::test_nothing_is_arranged_before_approval`, `::test_details_no_arrangement_depends_on_have_no_impact` | `change_impact.py::assess_change_impact` (`ARRANGED_STATUSES`) |
| The coordinator sees the impacts before deciding | `::test_pending_changes_are_listed_with_their_impact`, `EventChangeRequests.test.js` (impact describe block) | `change_request_service.py::list_change_requests`, `EventChangeRequests.vue` |
| Nothing is committed until every affected area is acknowledged, including one that appeared after the page loaded; what was acknowledged is recorded | `::test_approval_waits_until_every_affected_area_is_acknowledged`, `::test_an_impact_that_appears_after_the_page_loaded_must_be_acknowledged_too`, `::test_a_change_with_no_impact_is_approved_without_acknowledgement`, `::test_acknowledge_impacts_must_be_a_list_of_areas`, `::test_confirmed_event_changes_only_after_coordinator_approval` (409 then 200) | `change_impact.py::check_acknowledged`, `change_request_service.py::approve_change_request`, `event_change_requests.acknowledged_impacts` |

### IS-21 follow-up: event logs (what changed, who changed it, when)

Unit tests: `test_event_logs.py`, `frontend/src/components/EventLogHistory.test.js`. Integration: `test_event_change_requests_integration.py::test_change_request_round_trips_and_approval_writes_the_event`.

| Criterion | Test | Implementation |
|---|---|---|
| Each log entry records what changed (from -> to), who changed it and when, linked to the request's `shared_event_id` | `test_event_logs.py::test_entry_records_what_who_and_which_request`, `::test_diff_keeps_only_changed_fields_as_from_and_to`, `::test_diff_treats_the_same_instant_in_another_timezone_as_unchanged`, `::test_nothing_is_logged_when_nothing_changed`, `::test_a_legacy_event_is_logged_under_its_own_id` | `app/events/event_log.py::record_event_change`, `event_logs` table |
| Event logs and change requests are separate | `::test_requesting_a_change_is_logged_as_a_request_not_a_change`, `::test_a_rejected_change_request_adds_nothing_after_the_request`, `::test_an_approved_change_request_reads_requested_then_changed`, `::test_someone_who_is_both_organiser_and_coordinator_makes_changes`, `EventLogHistory.test.js` | `event_change_requests` (the requests) vs `event_logs` (timeline: requested / changed, `event_log.py::entry_kind`) |
| Every change to a submitted event is logged, whoever made it | `::test_a_shared_detail_is_written_to_every_session_but_logged_once`, `::test_coordinator_edit_is_logged`, `::test_organiser_fixing_a_rejected_session_is_logged`, `::test_draft_edits_are_not_logged`, `test_event_update.py::test_ac4_every_update_records_what_changed_who_changed_it_and_when` | `change_request_service.py::approve_change_request`, `event_update.py::update_event`, `routes.py::_log_direct_edit` (rejected session via the draft form) |
| Anyone who may view the event can read its history | `::test_log_is_the_whole_request_newest_first`, `::test_log_includes_who_made_each_change`, `::test_log_is_hidden_from_unrelated_users`, `EventLogHistory.test.js` | `GET /events/<id>/logs`, `event_log.py::list_event_logs`, `EventLogHistory.vue` |

### Room layouts managed by Venue Staff

Room layouts moved from the `room_layout` enum to the `room_layouts` table (`supabase/migrations/20261012000000_room_layouts.sql`). Unit tests: `test_room_layouts.py`. Integration: `test_room_layouts_integration.py`.

| Criterion | Test | Implementation |
|---|---|---|
| Venue Staff can add, update and delete room layouts; nobody else can | `test_room_layouts.py::test_only_venue_staff_manage_layouts`, the IS-60 `test_ac1_*` to `test_ac5_*` tests (incl. `::test_ac1_only_venue_staff_create_a_category`, `::test_ac2_only_venue_staff_edit_a_category`, `::test_ac3_only_venue_staff_disable_or_restore`, `::test_ac5_only_venue_staff_permanently_delete`) | `app/authz/rules.py::rule_room_layout_manage`, `app/room_layouts/routes.py` |
| Event forms read the active layouts | `::test_every_role_that_works_with_layouts_can_list_them`, `::test_ac3_a_disabled_category_is_no_longer_offered`, `::test_ac3_only_venue_staff_see_disabled_categories` | `GET /room-layouts`, `room_layout_service.py::list_room_layouts` |
| A soft-deleted layout can't be chosen, but events already using it keep it (submitting needs an active one) | `::test_a_soft_deleted_layout_cannot_be_chosen`, `::test_a_session_keeps_its_soft_deleted_layout_when_other_details_change`, `::test_a_draft_keeps_its_soft_deleted_layout_but_cannot_switch_to_one`, `::test_submitting_a_draft_whose_layout_was_soft_deleted_is_refused`, `::test_a_change_request_can_leave_a_soft_deleted_layout_alone_but_not_ask_for_one` | `app/events/event_service.py::_check_room_layout` |
| Permanent delete only once soft-deleted and every event using it is completed, cancelled or rejected; otherwise an error | `::test_ac4_an_active_category_cannot_be_permanently_deleted`, `::test_ac5_refused_while_an_ongoing_event_uses_it`, `test_room_layouts_integration.py::test_ac4_*`, `::test_ac5_*` | trigger `before_room_layout_delete`, `room_layout_service.py::delete_room_layout` (409) |
| Events that used a permanently deleted layout keep its name | `test_room_layouts_integration.py::test_ac5_allowed_once_its_events_are_finished_and_they_keep_its_name` | `events.room_layout` (name) + `room_layout_id` ON DELETE SET NULL, trigger `events_sync_room_layout` |
| Existing events point at the new table | `test_room_layouts_integration.py::test_the_existing_events_were_linked_by_the_migration`, `::test_an_event_written_with_a_layout_name_is_linked_to_its_row` | migration section 4 (backfill), trigger `events_sync_room_layout` |
| Renames reach events and venues' `supported_layouts`; a permanent delete removes the name from venues; a venue can only list layouts that exist | `test_room_layouts_integration.py::test_a_rename_reaches_linked_events_and_venues`, `::test_a_venue_can_only_list_layouts_that_exist` | `supabase/migrations/20261012100000_venue_supported_layouts.sql` (triggers `venues_check_supported_layouts`, `after_room_layout_rename_venues`, `after_room_layout_delete`) |
| Change requests use the managed layouts: a new layout can be requested, a soft-deleted one can't (and an approval is refused if it was soft-deleted while pending); a session keeps its soft-deleted layout when other details change | `test_event_change_requests.py::test_a_change_to_a_layout_venue_staff_added_is_recorded`, `::test_a_change_to_a_soft_deleted_layout_is_refused_and_nothing_is_recorded`, `::test_approval_is_refused_once_the_requested_layout_is_soft_deleted`, `::test_a_session_on_a_soft_deleted_layout_can_still_change_other_details` | `change_request_service.py::_validated_details`, `event_service.py::_check_room_layout` |
| Change impact checks any managed layout against the booked venue | `test_event_change_requests.py::test_a_layout_venue_staff_added_is_checked_against_the_booked_venue` | `change_impact.py::_venue_impacts` |
| A rename reaches pending change requests (so they can still be approved), not decided ones | `test_room_layouts_integration.py::test_a_rename_reaches_pending_change_requests_but_not_decided_ones` | trigger `after_room_layout_rename` |
| The event form offers the managed layouts and keeps a session's soft-deleted one | `frontend/src/components/EventSessionFields.test.js`, `frontend/src/lib/roomLayouts.test.js` | `EventSessionFields.vue`, `lib/roomLayouts.js` |
| Venue Staff manage room layouts from the frontend | `frontend/src/views/venues/RoomLayoutsView.test.js`, `frontend/src/lib/roles.test.js` (room-layouts route) | `RoomLayoutsView.vue`, `/room-layouts` route |
| Soft-deleting a layout clears it from drafts and rejected sessions (not from other submitted events); restoring doesn't put it back | `test_room_layouts_integration.py::test_ac3_disabling_clears_it_from_drafts_and_rejected_sessions_and_says_why` | `supabase/migrations/20261012200000_clear_draft_layouts_on_soft_delete.sql` (trigger `room_layout_soft_deleted`, extended to rejected sessions by `supabase/migrations/20261023000000_rejected_sessions_release_room_layouts.sql`) |
| Rejected sessions aren't ongoing: they don't hold up a permanent delete, and lose the layout when it's disabled, when they're rejected while it's disabled, or when it's permanently deleted | `test_room_layouts_integration.py::test_ac5_a_rejected_session_does_not_hold_up_the_delete_and_lets_go_of_it`, `::test_ac3_a_session_rejected_while_its_category_is_disabled_lets_go_of_it`, `::test_a_session_rejected_with_an_active_layout_keeps_it` | `supabase/migrations/20261023000000_rejected_sessions_release_room_layouts.sql` (triggers `before_room_layout_delete`, `room_layout_soft_deleted`, `events_release_disabled_layout_on_reject`) |
| The organiser is told why a draft or rejected session's layout is empty when Venue Staff removed it; the notice goes once a layout is chosen | `test_room_layouts_integration.py::test_choosing_a_layout_again_clears_the_removed_notice`, `EventSessionFields.test.js` (removed-layout notice), `lib/roomLayouts.test.js` (`removedLayoutNotice`), `lib/eventSessions.test.js` | `events.room_layout_removed` and trigger `events_unflag_removed_room_layout` (`supabase/migrations/20261023000000_rejected_sessions_release_room_layouts.sql`), `lib/roomLayouts.js::removedLayoutNotice`, `EventSessionFields.vue` |
| Submitting (or saving) a draft from a page that still shows a deleted layout is refused, telling the organiser to refresh and choose a new layout | `test_room_layouts.py::test_submitting_a_stale_draft_form_asks_to_refresh_and_choose_again`, `::test_creating_and_submitting_with_a_stale_layout_asks_to_refresh`, `::test_a_layout_name_that_no_longer_exists_asks_for_a_refresh` | `event_service.py::_check_room_layout` |

### IS-60 Venue Categories

Story: "As a Venue staff, I want to record what type of venues are available so that I can properly categorize the venues." Venue categories are the room layouts above (`room_layouts` table, `/room-layouts`); disabling a category is its soft delete. Ongoing events are those not completed, cancelled or rejected (rejected sessions are back with their organiser, like drafts). The tests live with the room layout tests, named by criterion (`test_ac1_*` ... `test_ac5_*`). Unit: `test_room_layouts.py`. Integration: `test_room_layouts_integration.py`.

| Criterion | Test | Implementation |
|---|---|---|
| AC1: Venue Staff can create a venue category | `test_room_layouts.py::test_ac1_*`, `test_room_layouts_integration.py::test_ac1_*`, `RoomLayoutsView.test.js` (adds a layout) | `POST /room-layouts`, `room_layout_service.py::create_room_layout` |
| AC2: Venue Staff can edit a venue category | `test_room_layouts.py::test_ac2_*`, `test_room_layouts_integration.py::test_ac2_*`, `RoomLayoutsView.test.js` (renames inline) | `POST /room-layouts/<id>`, `room_layout_service.py::rename_room_layout`, trigger `after_room_layout_rename` |
| AC3: A category can be disabled while ongoing events use it; they keep it, new events can't pick it | `test_room_layouts.py::test_ac3_*`, `test_room_layouts_integration.py::test_ac3_*`, `EventSessionFields.test.js` (removed-layout notice) | `DELETE /room-layouts/<id>`, `room_layout_service.py::soft_delete_room_layout`, `event_service.py::_check_room_layout`, trigger `room_layout_soft_deleted` |
| AC4: A category must be disabled before it can be permanently deleted | `test_room_layouts.py::test_ac4_*`, `test_room_layouts_integration.py::test_ac4_*` | `room_layout_service.py::delete_room_layout`, trigger `before_room_layout_delete` (23514) |
| AC5: Permanent delete once no ongoing event uses the disabled category | `test_room_layouts.py::test_ac5_*`, `test_room_layouts_integration.py::test_ac5_*`, `RoomLayoutsView.test.js` (shows the refusal) | `DELETE /room-layouts/<id>/permanent`, trigger `before_room_layout_delete` (23503; rejected sessions excluded and cleared, `supabase/migrations/20261023000000_rejected_sessions_release_room_layouts.sql`) |

## View Reserved Equipment (Justin, Sprint 3)

Story: "As a Coordinator, I want to see the quantity and which equipment is reserved for it, so that I know exactly what's allocated to the event." Unit tests: `test_equipment_service.py` (`list_requests_for_event`), `test_event_equipment_requests_routes.py` (route + authz), `frontend/src/lib/equipment.test.js`, `frontend/src/components/EquipmentBookingStatus.test.js`. Integration: `test_equipment_requests_for_event_integration.py`.

| Criterion | Test | Implementation |
|---|---|---|
| Confirmed equipment reservations display quantity per item | `test_equipment_service.py::test_confirmed_request_lists_reserved_units_by_type_then_asset_tag`, `::test_allocated_quantity_counts_units_held_not_units_asked_for`, `equipment.test.js::allocatedEquipment`, `EquipmentBookingStatus.test.js` ("lists the reserved units by type, with quantity and asset tags, once confirmed"), `test_equipment_requests_for_event_integration.py::test_confirmed_request_lists_reserved_units_by_type_from_the_real_database` | `equipment_service.py::_allocated_units` / `list_requests_for_event`, `lib/equipment.js::allocatedEquipment`, `EquipmentBookingStatus.vue` |
| Specific equipment IDs are listed alongside the quantity | `test_equipment_service.py::test_confirmed_request_lists_reserved_units_by_type_then_asset_tag`, `EquipmentBookingStatus.test.js` (same test), `test_equipment_requests_for_event_integration.py::test_confirmed_request_lists_reserved_units_by_type_from_the_real_database` | `_allocated_units` (unit `id` + `asset_tag`, sorted by tag), `EquipmentBookingStatus.vue` |
| Details are visible on the event request view once the reservation is confirmed | `test_equipment_service.py::test_only_confirmed_requests_show_allocated_units`, `EquipmentBookingStatus.test.js` ("shows no allocated equipment while requests are only pending"), `test_event_equipment_requests_routes.py::test_event_equipment_requests_for_assigned_coordinator`, `::test_event_equipment_requests_404_for_coordinator_not_assigned` | `GET /events/<id>/equipment-requests` (`event.view`), `EventDetailsView.vue` (coordinator view, below Venue Booking) |
| (design) Every request for the event is listed with what was asked for, total quantity, when it is needed and its status, newest first | `test_equipment_service.py::test_event_requests_are_scoped_to_the_event_and_newest_first`, `::test_event_request_totals_the_quantity_asked_for`, `::test_event_with_no_requests_returns_empty_list`, `EquipmentBookingStatus.test.js` ("shows each request with its items, total quantity and status", "says so when nothing has been requested") | `list_requests_for_event` (`items`, `total_quantity`), `EquipmentBookingStatus.vue` table |
| (design) On a cancelled event, confirmed requests read "Released" and no units are listed | `equipment.test.js::eventRequestStatus`, `::allocatedEquipment` ("lists nothing once the event is cancelled"), `test_equipment_service.py::test_confirmed_request_with_released_units_has_nothing_allocated`, `EquipmentBookingStatus.test.js` ("marks confirmed requests released...") | `lib/equipment.js::eventRequestStatus` / `allocatedEquipment` |

Not covered here: actually releasing the units when an event is cancelled (deleting its reservation rows) -- that is the separate "release equipment on cancel" story. Reservation rows are still written only by `backend/seed.py` until "Accept an equipment request" is built (see `docs/design-decisions.md` §View Reserved Equipment for the conventions this relies on).

## Release Equipment on Cancel (Justin, Sprint 3)

Story: "As a Technical Staff member, I want reserved equipment to be released automatically when an event is cancelled, so that the stock becomes available again for other events." Unit tests: `test_reservation_release.py`, `test_event_lifecycle.py` (when the route releases). Integration: `test_reservation_release_integration.py`. Both guards below were mutation-tested by hand (broken, caught, restored).

| Criterion | Test | Implementation |
|---|---|---|
| Cancelling an event releases all equipment reserved for it | `test_reservation_release.py::test_cancelling_releases_every_unit_reserved_for_the_event`, `::test_other_events_reservations_are_left_alone`, `::test_requests_and_their_lines_are_kept`, `::test_releasing_twice_is_harmless`, `test_event_lifecycle.py::test_cancelling_releases_the_events_equipment`, `test_reservation_release_integration.py::test_cancelling_an_event_gives_its_units_back_for_that_date_and_time` | `app/equipment/reservation_release.py::release_event_equipment`, `app/events/routes.py::cancel_event` |
| Available quantity is recalculated and updated for the cancelled event's date and time | `test_reservation_release_integration.py::test_cancelling_an_event_gives_its_units_back_for_that_date_and_time` (availability for an overlapping request goes 0 -> 1, and the unit can be reserved again) | availability is counted from reservation rows: `equipment_service.py::check_availability`, exclusion constraint `equipment_reservations_no_unit_overlap` |
| (design) Nothing is released unless the cancel itself succeeded | `test_event_lifecycle.py::test_a_cancel_refused_for_no_reason_releases_nothing`, `::test_a_cancel_refused_by_status_releases_nothing`, `::test_a_cancel_that_lost_a_race_releases_nothing`, `::test_other_lifecycle_moves_do_not_release_equipment` | `cancel_event` calls the release after `transition()` |
| (design) The event page shows the request as Released | covered by View Reserved Equipment (`EquipmentBookingStatus.test.js`) | `lib/equipment.js::eventRequestStatus` |
| (design) The assigned coordinator can cancel a session from the event page, with a reason, and is told how many units were released | `frontend/src/views/events/CoordinatorEventReview.test.js` (offered only for approved / planning / confirmed; reason required; posts the reason; reports released units; keeps the panel open on error) | `CoordinatorEventReview.vue` "Cancel Event" (calls IS-39's `POST /events/<id>/cancel`) |

## Reassignment is Lead-only (Week 9 clarification, Justin, Sprint 3)

Week 9 (Sreya): "Is the reassignment of coordinators now handled by Event Coordinator Lead role instead of offline agreement by coordinators?" — "yes, it is now manually assigned by the lead". This **supersedes** the Sprint 1 story "Coordinator needs reassignment" ("As an Event Coordinator, I want to reassign an associated event...") and the Week 4 answer it was built on. Its other criteria (one coordinator at a time; the new one takes over; the previous one is unassigned) still hold, now for the Lead's reassignment — `coordinator_service.reassign_coordinator` is unchanged.

| Criterion | Test | Implementation |
|---|---|---|
| Only the Event Coordinator Lead can reassign; the event's coordinator and organiser get 403, anyone else 404 | `test_coordinator_lead.py::test_only_the_lead_reassigns_week_9`, `test_authz_policy.py::test_coordinator_denied_reassign_even_when_currently_assigned`, `test_events_routes.py::test_reassign_route_refuses_the_events_own_coordinator`, `::test_reassign_route_succeeds_for_the_lead` | `rules.py::rule_event_reassign_coordinator`, `routes.py::reassign_coordinator_route` (`requested_by=None`) |
| The Lead can reassign after venue and technical arrangements are confirmed (Week 9, Shanise); not once completed (IS-38) | `test_coordinator_lead.py::test_lead_may_reassign_after_arrangements_are_confirmed`, `test_event_lifecycle.py::test_reassign_still_allowed_before_completion`, `::test_is38_reassign_route_refused_on_completed_event` | `rule_event_reassign_coordinator` |
| Coordinators no longer list other coordinators (only the Lead picks) | `test_coordinator_lead.py::test_coordinators_no_longer_list_other_coordinators`, `test_event_decisions.py::test_coordinator_list_rule_allows_only_the_lead`, `::test_coordinators_route_lists_for_lead` | `rules.py::rule_coordinator_list` |
| No Reassign in the coordinator's UI | `frontend/src/views/events/CoordinatorEventReview.test.js` ("no Reassign"), `frontend/src/router/index.test.js` ("the old coordinator-only /events/reassign page is gone"), `frontend/src/lib/roles.test.js` | Reassign panel removed from `CoordinatorEventReview.vue`; `ReassignCoordinatorView.vue`, its route and `ROUTE_ACCESS` entry deleted |

The rule change was mutation-tested by hand: restoring the "current coordinator may reassign" branch fails the three coordinator-denied tests above.

## Update Event Information During Planning (IS-9, Sprint 3)

Unit tests: `test_event_update.py` (one section per criterion), `test_venue_booking_cancel.py` (AC9: service, rule, route), `test_event_logs.py` ("which session each entry is about"), `frontend/src/lib/eventUpdates.test.js`, `frontend/src/views/events/CoordinatorEventReview.test.js` ("Edit Details (IS-9)"), `frontend/src/components/VenueBookingStatus.test.js`, `frontend/src/views/events/EventDetailsView.test.js` (AC5), `frontend/src/lib/venueBookings.test.js`, `frontend/src/components/EventLogHistory.test.js`. Integration (local Supabase): `test_is9_integration.py`, `test_event_change_requests_integration.py`. Design reasoning: `docs/design-decisions.md` §Update Event Information During Planning (IS-9).

| Acceptance criterion | Test | Implementation |
|---|---|---|
| Can update name, description, category, preferred dates and times, expected attendance, venue requirements and accessibility needs while in a planning stage | `test_event_update.py::test_ac1_the_coordinator_updates_each_detail_during_planning[*]`, `::test_ac1_updates_are_open_until_the_event_is_finished[*]`, `::test_the_coordinator_edit_form_payload_is_saved` | `POST /events/<id>`, `app/events/event_update.py::update_event`; `CoordinatorEventReview.vue` (Edit Details) |
| Date, time, expected attendance, venue requirements or equipment changes are recorded as significant; others as ordinary | `::test_ac2_each_update_is_recorded_as_significant_or_ordinary[*]`, `::test_ac2_the_history_reports_significance_even_for_older_entries`, `test_event_logs.py::test_entry_records_what_who_and_which_request`, `test_is9_integration.py::test_a_change_to_a_confirmed_event_is_logged_significant_and_sends_it_back_to_planning`, `::test_an_ordinary_change_is_stored_as_ordinary`, `EventLogHistory.test.js` (significance) | `event_log.py::SIGNIFICANT_FIELDS` / `significance`, `event_logs.significance` (`20261015000000_event_logs_significance.sql`) |
| Before a significant change is committed, the coordinator is shown which arrangements it touches (venue, equipment, technical support, registration) | `::test_ac3_arrangements_that_still_fit_are_presented_too`, `::test_ac3_registrations_are_presented_when_attendance_changes`, `::test_ac3_an_equipment_change_touches_equipment_requests_not_the_venue`, `::test_ac3_an_ordinary_change_touches_no_arrangement`, `::test_ac3_cancelled_and_rejected_arrangements_are_not_presented`, `::test_ac3_no_arrangements_are_presented_before_planning[*]`, `::test_ac3_arrangements_are_presented_through_the_preview_route`, `::test_ac3_identical_equipment_requests_are_reported_once_not_once_each`, `::test_ac3_a_single_equipment_request_is_described_in_the_singular`, `test_is9_integration.py::test_the_preview_names_the_booked_venue_a_change_touches`, `eventUpdates.test.js` (`arrangementsOfPreview`), `CoordinatorEventReview.test.js` ("presents every arrangement...", "flags the touched arrangement that conflicts"), `::test_ac3_the_preview_presents_every_arrangement_the_change_touches`, `::test_ac3_a_significant_change_is_not_committed_until_its_impacts_are_acknowledged`, `::test_ac3_once_acknowledged_the_change_is_saved_with_what_was_acknowledged`, `::test_ac3_a_change_that_touches_nothing_arranged_needs_no_acknowledgement`, `::test_ac3_equipment_requests_already_made_are_checked_against_the_new_timing`, `::test_ac3_impacts_are_checked_through_the_route_too`, `::test_ac3_before_planning_the_coordinator_edits_freely[*]`, `::test_ac3_from_planning_on_impacts_are_checked[*]`, `eventUpdates.test.js` (`needsReview`), `CoordinatorEventReview.test.js` (review step) | `POST /events/<id>/update-preview` (`event_update.py::preview_event_update`, `arrangements` + `impacts`), `event_update.py::IMPACT_CHECKED_STATUSES`, `change_impact.py::touched_arrangements` (every arrangement touched, conflict or not), `::assess_change_impact` / `check_acknowledged` (the conflicts, which must be acknowledged); "Arrangements this change touches" and review panel in `CoordinatorEventReview.vue`, `lib/eventUpdates.js::arrangementsOfPreview` |
| Every update records what changed, who changed it and when (and on which session) | `::test_ac4_every_update_records_what_changed_who_changed_it_and_when`, `::test_ac4_an_update_that_changes_nothing_writes_nothing`, `test_event_logs.py::test_entry_records_what_who_and_which_request`, `::test_a_coordinator_edit_records_the_session_it_was_made_on`, `::test_the_history_labels_each_entry_with_its_session_in_date_order`, `::test_a_shared_detail_change_is_labelled_all_sessions`, `test_is9_integration.py::test_an_update_is_logged_against_its_session_and_labelled_in_the_history`, `::test_a_history_entry_outlives_its_deleted_session`, `EventLogHistory.test.js` (session badge, pagination) | `event_log.py::record_event_change` / `record_requested_change` (`event_logs`, `event_id` from `20261019400000_event_logs_session.sql`), `event_log.py::list_event_logs` (`session` label); `EventLogHistory.vue` (5 per page, `lib/pagination.js`) |
| Only the event's coordinator may update it; others can view but not edit | `::test_ac5_others_who_can_view_the_event_cannot_update_it[*]` (organiser, Lead: GET 200, POST 403), `::test_ac5_another_coordinator_cannot_see_or_update_the_event` (404), `test_event_submission.py::test_is31_organizer_cannot_edit_a_submitted_request_directly`, `EventDetailsView.test.js` ("who may edit": coordinator gets the review page, organiser edits only a draft/rejected session, organiser/Lead/other coordinator read-only) | `rules.py::rule_event_edit` (Lead now 403, not 404); `EventDetailsView.vue` (`isAssignedCoordinator`, `mode`) |
| An update that fails validation leaves the stored event unchanged | `::test_ac6_an_update_that_fails_validation_leaves_the_event_unchanged[*]`, `::test_ac6_a_failed_update_through_the_route_is_a_400`, `::test_ac6_an_update_racing_a_status_change_is_refused_not_overwritten`, `::test_an_update_to_a_session_that_no_longer_exists_is_refused` | `event_update.py::_validated` (merged onto stored details, validated before any write); write conditional on status |
| Once completed or cancelled, update attempts are refused with a reason | `::test_ac7_a_finished_event_refuses_updates_with_the_reason[*]`, `CoordinatorEventReview.test.js` ("shows the refusal reason", "offers no Edit Details") | `rules.py::explain_event_edit_denial`, `policy.py::_DENIAL_REASONS` |
| Important actions are recorded for auditability | `::test_ac3_once_acknowledged_the_change_is_saved_with_what_was_acknowledged` (`acknowledged_impacts`), `::test_ac10_a_change_to_a_confirmed_event_sends_it_back_to_planning` (status history with reason) | `event_logs.acknowledged_impacts`, `event_status_log` via `transitions.transition` |
| Changing or cancelling one venue arrangement doesn't remove the other bookings | `::test_ac9_a_change_affecting_one_venue_booking_leaves_every_booking_in_place`, `test_venue_booking_cancel.py::test_cancelling_one_booking_leaves_every_other_booking_untouched`, `::test_only_the_cancelled_booking_is_written`, `::test_the_event_status_is_not_changed_by_cancelling_a_booking`, `::test_a_cancellation_is_recorded_with_who_when_and_why`, `::test_a_cancel_racing_a_status_change_is_refused_not_overwritten`, `::test_the_route_cancels_one_booking_and_leaves_the_rest`, authz `::test_*cancel*`, `test_is9_integration.py::test_cancelling_one_booking_leaves_the_sessions_other_bookings_in_place`, `::test_a_cancelled_booking_frees_the_venue_for_another_event`, `VenueBookingStatus.test.js` ("cancels one booking and leaves the others exactly as they were") | Change: `change_impact.py` (read-only, per booking); nothing in `event_update.py` writes `venue_bookings`. Cancel: `POST /venues/bookings/<id>/cancel` (`venues/routes.py::cancel_venue_booking_route`), `booking_service.py::cancel_booking` (one row, conditional on its status, reason in `venue_booking_status_log`), `rules.py::rule_venue_booking_cancel`, `'cancelled'` status (`20261019300000_venue_booking_cancel.sql`); per-booking Cancel in `VenueBookingStatus.vue` |
| Any change after confirmation reverts the event to planning | `::test_ac10_a_change_to_a_confirmed_event_sends_it_back_to_planning`, `test_is9_integration.py::test_a_change_to_a_confirmed_event_is_logged_significant_and_sends_it_back_to_planning` (real `event_status_log` row), `::test_ac10_the_preview_warns_that_a_confirmed_event_will_go_back_to_planning`, `::test_ac10_only_a_confirmed_event_changes_status[*]`, `::test_ac10_saving_a_confirmed_event_unchanged_keeps_it_confirmed`, `::test_a_new_name_reaches_every_open_session_of_the_request`, `test_event_change_requests.py::test_confirmed_event_changes_only_after_coordinator_approval`, `test_transitions.py::test_edge_set_is_exactly_the_sourced_edges` | `transitions.py` edge `confirmed -> planning`, `event_update.py::revert_to_planning` (also used by `approve_change_request`) |

## View Equipment Availability Calendar (IS-47, Sprint 3)

Unit tests: `test_equipment_calendar_service.py` (service, including the boundary cases), `test_equipment_calendar_routes.py` (route), `test_authz_equipment_calendar.py` (rule); integration: `test_equipment_calendar_integration.py` (the reservation -> request -> event join against local Postgres); frontend: `EquipmentCalendarView.test.js`, `lib/calendar.test.js` (`monthCells` with `spanDays`, `widenRange`), `lib/roles.test.js` and `router/index.test.js` (route access).

| Criterion | Test | Implementation |
|---|---|---|
| AC1 Technical Support Staff can open a unit and see its reservation calendar | `test_equipment_calendar_routes.py::test_route_succeeds_for_technical_staff`, `test_authz_equipment_calendar.py::test_technical_staff_allowed_calendar_view`, `router/index.test.js` ("technical_support_staff reaches /equipment/unit-1/calendar"), `EquipmentCalendarView.test.js` | `GET /equipment/<id>/calendar` (`equipment/calendar_routes.py::get_equipment_calendar_route`), `equipment/calendar_service.py::get_equipment_calendar`, `EquipmentCalendarView.vue` (route `equipment-calendar`), link on `EquipmentDetailView.vue` (pending Nawaz's sign-off; without it the page is reached by URL only) |
| AC2 Page shows asset tag, type, description/notes, location and current status | `test_equipment_calendar_service.py::test_response_carries_the_unit_profile_and_the_range`, `EquipmentCalendarView.test.js` ("shows the asset tag, type, status pill and the profile") | `calendar_service.py` resource block; profile block and status pill in `EquipmentCalendarView.vue`. **Location is not shown: `equipment_units` has no location column** (docs/open-questions.md) |
| AC3 One month at a time, with previous/next | `EquipmentCalendarView.test.js` ("shows one month, and previous/next fetch the neighbouring months"), `lib/calendar.test.js` (`stepAnchor`, `rangeFor`) | `useCalendarRange('month')`, `AvailabilityCalendar` with `view="month"` |
| AC4 Every day with a confirmed reservation is marked with the event's name | `test_equipment_calendar_service.py::test_reservation_within_range_is_an_entry_naming_its_event`, `::test_reservations_outside_the_range_are_excluded`, `test_equipment_calendar_integration.py::test_calendar_entries_name_the_event_through_the_real_join`, `EquipmentCalendarView.test.js` ("marks every day...", "a reservation on the last day of the month is marked", "asks for a range that covers the whole local month") | `equipment_service.get_equipment` (occupancy with event name), `calendar_service.py` (`CalendarRange.overlaps`), `widenRange` in `lib/calendar.js` |
| AC5 A multi-day reservation is marked on every day it covers | `test_equipment_calendar_service.py::test_multi_day_reservation_is_one_entry_with_its_whole_period`, `::test_multi_day_reservation_starting_before_the_range_is_included`, `lib/calendar.test.js` ("monthCells with spanDays"), `EquipmentCalendarView.test.js` ("marks every day of a multi-day reservation") | `monthCells(range, entries, { spanDays: true })`, `AvailabilityCalendar` `span-days` prop |
| AC6 Only Technical Support Staff; anyone else gets the same response as an unknown unit | `test_authz_equipment_calendar.py::test_every_other_role_denied_calendar_view[*]`, `::test_denial_is_a_404_not_a_403[*]`, `test_equipment_calendar_routes.py::test_route_is_404_for_every_other_role`, `::test_a_hidden_unit_and_an_unknown_unit_get_the_same_response`, `lib/roles.test.js` (equipment calendar), `router/index.test.js` (non-staff redirected) | `rules.py::rule_equipment_calendar_view` (`DENY_NOT_FOUND`), `calendar_routes.py::load_unit` (same 404 message as `authorise()`), `ROUTE_ACCESS` `equipment-calendar` |
| AC7 Unknown unit -> 404; missing or malformed dates -> 400 | `test_equipment_calendar_routes.py::test_route_returns_404_for_an_unknown_unit`, `::test_route_requires_start_and_end`, `::test_route_rejects_malformed_dates_and_end_before_start`, `test_equipment_calendar_service.py::test_rejects_end_before_start`, `::test_rejects_malformed_date[*]`, `test_equipment_calendar_routes.py::test_route_rejects_unauthenticated` (401) | `calendar_routes.py::load_unit`, route's missing-parameter check, `shared/calendar.py::parse_calendar_range` |
| Range edges (not an AC; DoD boundary tests) | `test_equipment_calendar_service.py::test_reservation_ending_exactly_at_the_range_start_is_excluded`, `::test_reservation_starting_exactly_at_the_range_end_is_excluded`, `::test_reservation_starting_at_the_ranges_last_instant_is_excluded`, `::test_reservation_covering_the_range_exactly_is_included`, `::test_reservations_just_inside_each_edge_are_included` | `shared/calendar.py::spans_overlap` via `CalendarRange.overlaps` |

Not built, so not tested: a "pending" state and dated maintenance periods on the calendar, and the unit's location (see `docs/open-questions.md`).

## Event statuses: a defined set (Event Status Management), plus `safety_review` (Week 7 #6)

Story: "As an Event Coordinator, I want the system to support a defined set of event statuses, so that everyone uses a consistent, shared vocabulary for where an event stands." AC2 reworded from "each event request" to "each event session": every session of a multi-session request is its own `events` row and moves through the statuses on its own (see `docs/design-decisions.md`).

| Criterion | Test | Implementation |
|---|---|---|
| AC1 The system supports exactly these statuses: draft, submitted, under review, approved, planning, safety review, confirmed, completed, cancelled, rejected | `test_transitions.py::test_status_vocabulary_is_exactly_the_defined_set`, `::test_every_edge_uses_only_defined_statuses` | `public.event_status` (`20260911120000_init_users_events.sql`, plus `safety_review` in `20261018000000_event_status_safety_review.sql`); `transitions.py::_LABELS`; `event_service.py::EVENT_STATUSES` |
| AC2 Each event session has exactly one status at a time | `test_transitions_integration.py::test_concurrent_transitions_from_same_status_exactly_one_wins`, `::test_many_identical_concurrent_transitions_exactly_one_wins` | `events.status` is a single `not null` column of type `event_status`; every change goes through `transitions.transition` (conditional update) |
| AC3 The status is visible wherever the event request is displayed | Manual check (no component tests for these views, per the frontend convention); `coordinatorDashboard.test.js` (`tabForStatus`, including `safety_review`) | status badge in `EventsListView.vue`, `EventDetailsView.vue`, `CoordinatorEventReview.vue`, `CoordinatorDashboard.vue`, `LeadDashboard.vue`, `SessionSummaryCard.vue`, `EventSessionFields.vue`; `.status-safety_review` style in each place that has a status palette |
| Week 7 #6: safety_review sits between planning and confirmed; rejected or changes requested go back to planning | `test_transitions.py::test_edge_set_is_exactly_the_sourced_edges`, `::test_every_legal_edge_is_allowed[*safety_review*]`, `::test_representative_illegal_edges_are_refused` (`under_review -> safety_review`, `safety_review -> completed`) | `transitions.py` edges `planning -> safety_review`, `safety_review -> confirmed`, `safety_review -> planning`, `safety_review -> cancelled` |

The Safety Officer role, its queue and its decisions were built afterwards -- see "Safety Officer: Operational Feasibility Check" below.

## Safety Officer: Operational Feasibility Check (Week 7 #6, Justin, Sprint 3)

Source: Week 7 Customer Changes #6, plus the Week 9 answers (Sreya, Jin
Hong). Unit tests: `test_safety_service.py` (service), `test_authz_safety_reviews.py`
(rules), `test_safety_routes.py` (routes), `test_event_lifecycle.py` (confirm
gate). Integration: `test_safety_reviews_integration.py` (local Supabase).
Frontend: `lib/safetyReviews.test.js`, `components/SafetyCheckStatus.test.js`,
`views/safety/SafetyReviewView.test.js`, `lib/roles.test.js`. The four guards
marked (guard) were mutation-tested by hand (broken, caught, restored).

| Criterion | Test | Implementation |
|---|---|---|
| "ConnectSphere has introduced a new internal role, the Safety Officer" | `test_authz_safety_reviews.py::test_safety_officer_may_list_and_view`, `roles.test.js` (safety_officer) | `app_role` value `safety_officer` (`20261019000000_safety_officer.sql`); `ROLES.SAFETY_OFFICER`; seeded `safety1@example.com` |
| "After the venue and technical arrangements have been confirmed, the Safety Officer must conduct an Operational Safety Check" -- the coordinator submits once the arrangements are confirmed | `test_safety_service.py::test_submit_writes_a_pending_review_and_moves_the_session_to_safety_review`, `::test_submit_refused_when_arrangements_are_not_ready` (guard), the `arrangement_problems` tests, `test_safety_routes.py` (submit), `test_safety_reviews_integration.py::test_submit_writes_a_pending_review_the_officer_sees_with_its_session`, `SafetyCheckStatus.test.js` | `POST /events/<id>/safety-review`, `safety_service.submit_for_safety_check` / `arrangement_problems`, `rule_safety_review_submit`, edge `planning -> safety_review`, `SafetyCheckStatus.vue` |
| Week 9: "The safety officer role will pick up the event request" -- the officer's queue | `test_safety_service.py::test_list_embeds_each_session_and_hides_pending_reviews_of_sessions_that_moved_on`, `::test_list_is_empty_for_anyone_but_a_safety_officer`, `test_safety_routes.py` (list), `safetyReviews.test.js` (tabs, rows) | `GET /safety-reviews`, `safety_service.list_reviews`, `SafetyOfficerDashboard.vue` (Check Safety / Checked) |
| "The review considers ... expected attendance, venue capacity and layout, ... accessibility requirements, equipment placement ..." | `test_safety_reviews_integration.py::test_approval_opens_confirmation_and_the_detail_shows_the_venue`, `SafetyReviewView.test.js` ("shows what to check") | `GET /safety-reviews/<id>`, `safety_service.review_detail`, `SafetyReviewView.vue` (+ `checkSuitability`) |
| "The Safety Officer may approve the event, reject the safety arrangement, or request changes" -- with a comment (Week 9) | `test_safety_service.py` (decide tests), `test_safety_routes.py::test_each_decision_route_passes_its_status_and_the_comment`, `SafetyReviewView.test.js` | `POST /safety-reviews/<id>/approve`, `/reject`, `/request-changes`, `safety_service.decide_review`, `rule_safety_review_*` |
| "If changes are required, the event returns to the relevant earlier planning stage" (Week 9: back to planning) | `test_safety_service.py::test_reject_or_request_changes_sends_the_session_back_to_planning_with_the_comment`, `test_safety_reviews_integration.py::test_changes_requested_goes_back_to_planning_and_a_resubmission_is_a_new_review` | edge `safety_review -> planning`, `decide_review` |
| "The event cannot proceed to preparation until the Safety Officer has approved it" -- confirm only once approved, and nothing skips the check | `test_event_lifecycle.py::test_confirm_refused_until_the_safety_officer_approves` (guard), `::test_confirm_from_planning_is_refused`, `test_transitions.py::test_representative_illegal_edges_are_refused` (`planning -> confirmed`), `test_authz_safety_reviews.py::test_confirm_is_from_safety_review_only`, `SafetyCheckStatus.test.js` ("confirms an approved session") | `confirm_event` + `safety_service.is_approved`, `rule_event_confirm` (from `safety_review`), no `planning -> confirmed` edge |
| (design) One pending review per session; two decisions can't both land | `test_safety_reviews_integration.py::test_the_database_allows_only_one_pending_review_per_session`, `test_safety_service.py::test_a_second_pending_review_is_refused_clearly`, `::test_a_second_decision_racing_the_first_is_refused` (guard) | unique index `safety_reviews_one_pending_per_event`; conditional update in `decide_review` |
| (design) A refused submit leaves nothing behind | `test_safety_service.py::test_a_submit_whose_status_change_fails_leaves_no_review_behind` (guard) | `submit_for_safety_check` deletes the review if the transition fails |
| (design) A session in safety review can still be cancelled; change requests stay open | `test_authz_safety_reviews.py::test_a_session_in_safety_review_can_still_be_cancelled`, `::test_change_requests_stay_open_during_safety_review`, `test_event_lifecycle.py::test_is39_coordinator_can_cancel_after_approval[safety_review]` | `_CANCELLABLE_STATUSES`, `CHANGE_REQUEST_STATUSES` |

Not built, so not tested: notifications for submissions and decisions, and
resetting a check when a session is edited during it (see
`docs/open-questions.md`, "Safety Officer").

## Sprint 3 — Record Equipment Request for Event (IS-17, Nawaz)

Source: IS-17's AC, plus Aaralyn's IS-9 note that equipment requests need
planning. Unit tests: `test_equipment_create_request.py` (service),
`test_authz_equipment_create.py` (rules), `test_equipment_create_routes.py`
(routes). Frontend: `lib/equipment.test.js`,
`views/equipment/RequestEquipmentView.test.js`,
`components/EquipmentBookingStatus.test.js`, `lib/roles.test.js`,
`router/index.test.js`. Not tested against a real database.

| Criterion | Test | Implementation |
|---|---|---|
| "Can specify an event and specify one or more equipment items required for it" | `test_equipment_create_request.py::test_creates_a_pending_request_for_the_event_with_its_lines`, `::test_needs_at_least_one_item`, `RequestEquipmentView.test.js` ("submits every line and returns to the event page", "can remove an added line but never the last one") | `POST /events/<id>/equipment-requests`, `equipment_service.create_request`, `RequestEquipmentView.vue` |
| "Can specify the quantity needed for each equipment item" | `test_equipment_create_request.py::test_creates_a_pending_request_for_the_event_with_its_lines`, `test_equipment_create_request.py::test_a_type_can_only_appear_once` | `_validate_request_items`, one `equipment_request_items` row per type |
| "Can enter free-text technical requirements for each equipment item" | `test_equipment_create_request.py::test_blank_requirements_are_stored_as_null_and_text_is_trimmed`, `::test_requirements_must_be_text_and_within_the_limit` | `technical_requirements` on each line, 2000 character cap |
| "System prevents submitting a request if quantity is missing or zero for a selected equipment item" | `test_equipment_create_request.py::test_quantity_must_be_a_whole_number_of_at_least_one`, `::test_missing_quantity_key_is_rejected`, `equipment.test.js` (validateRequestLines), `RequestEquipmentView.test.js::blocks submit and shows the error when quantity is missing or zero` | `validateRequestLines` (client) and `_validate_request_items` (server) |
| "Submitted equipment request is viewable later" | `EquipmentBookingStatus.test.js` ("shows each request with its items, total quantity and status"), existing `test_equipment_service.py` list/get tests | Equipment Booking section (Justin, `GET /events/<id>/equipment-requests`), Technical Support queue (IS-18) |
| "When it's created, its status is set to Pending and is visible to relevant Technical Staff" | `test_equipment_create_request.py::test_creates_a_pending_request_for_the_event_with_its_lines` | status `pending` on insert; queue is IS-18's `GET /equipment/requests` |
| (design) Only the assigned coordinator, only while planning | `test_authz_equipment_create.py` (all), `test_equipment_create_routes.py` (403 outside planning, 404 for a stranger), `EquipmentBookingStatus.test.js` ("requesting equipment") | `rule_equipment_request_create`, `canRequest` in `EquipmentBookingStatus.vue` |
| (design) A request is for the session's own window | `test_equipment_create_request.py::test_needed_period_is_the_sessions_own_window_in_singapore_time`, `::test_session_with_no_times_needs_equipment_all_day` | `booking_service._event_window` |
| (design) No half-created request | `test_equipment_create_request.py::test_request_row_is_deleted_if_its_lines_cannot_be_saved` | compensating delete in `create_request` |
| (design) Coordinators can read the type catalogue | `test_authz_equipment_create.py` (type list), `test_equipment_create_routes.py` (types) | `GET /equipment/types`, `rule_equipment_type_list` |

## Sprint 3 — Accept an Equipment Request and Reserve Stock (IS-19, Nawaz)

Source: the Reservation story's first AC. Unit tests:
`test_equipment_accept.py` (service), `test_authz_equipment_accept.py`
(rule), `test_equipment_accept_routes.py` (route). Frontend:
`views/equipment/EquipmentRequestDetailView.test.js`. Not tested against a
real database.

| Criterion | Test | Implementation |
|---|---|---|
| "Accepting a request changes its status to confirmed" | `test_equipment_accept.py::test_accept_reserves_one_row_per_unit_and_confirms_the_request`, `::test_reserves_the_reservations_before_flipping_the_status`, `test_equipment_accept_routes.py::test_technical_staff_accept_returns_the_confirmed_request` | `POST /equipment/requests/<id>/accept`, `equipment_service.accept_request` |
| "Available quantity for that equipment is reduced by the reserved amount, scoped to the event's date and time" | `test_equipment_accept.py::test_each_reservation_copies_the_requests_period`, `::test_skips_units_held_for_an_overlapping_event_and_units_out_of_service`, `::test_a_unit_returned_when_the_request_starts_is_free` | one `equipment_reservations` row per unit copying `needed_start`/`needed_end`; availability is counted, not stored |
| "Only requests in a pending status can be accepted" | `test_authz_equipment_accept.py::test_only_a_pending_request_can_be_accepted`, `test_equipment_accept_routes.py::test_an_already_confirmed_request_is_403`, `::test_a_second_accept_racing_the_first_releases_what_it_reserved` (guard) | `rule_equipment_request_accept`; status update conditioned on `pending` |
| (design) Technical Support only | `test_authz_equipment_accept.py::test_other_roles_cannot_accept_and_get_a_404`, `test_equipment_accept_routes.py::test_a_coordinator_cannot_accept` | `rule_equipment_request_accept` |
| (design) Not for a request whose event has left planning | `test_authz_equipment_accept.py::test_a_request_is_only_accepted_while_its_event_is_in_planning`, `test_equipment_accept_routes.py::test_a_cancelled_events_request_is_403` | `get_request` carries `event_status`; the rule checks it |
| (design) Accepted whole or not at all; says what is short | `test_equipment_accept.py::test_refuses_when_there_is_not_enough_and_says_what_is_short`, `::test_one_short_line_means_nothing_is_reserved_for_any_line` (guard) | `accept_request` checks every line before writing |
| (design) Two requests cannot take the same unit | `test_equipment_accept.py::test_the_exclusion_constraint_refusing_a_unit_is_a_clear_error`, `::test_a_failure_flipping_the_status_also_releases_the_units` | exclusion constraint `equipment_reservations_no_unit_overlap`; clean-up in `accept_request` |
| Technical Support can accept from the request page and sees what was reserved | `EquipmentRequestDetailView.test.js` ("accepting the request": enabled/disabled button, no decision once decided, accepts and lists units, shows the server error) | `EquipmentRequestDetailView.vue` "Your decision" and "Reserved for this event" |

## Sprint 3 — Get Warned and Reject When Requested Quantity Exceeds Availability (IS-41, Nawaz)

Source: the Reservation story's second sub-story. Unit tests:
`test_equipment_reject.py` (service), `test_authz_equipment_reject.py`
(rule), `test_equipment_reject_routes.py` (route). Frontend:
`EquipmentRequestDetailView.test.js` ("rejecting the request"),
`EquipmentBookingStatus.test.js`. Needs migration
`20261019100000_equipment_request_rejection.sql`. Not tested against a real
database.

| Criterion | Test | Implementation |
|---|---|---|
| "The system shows the actual available quantity when a request exceeds it" | `EquipmentRequestDetailView.test.js::suggests rejecting and shows the available quantity when stock is short` (the numbers themselves are IS-18's check) | per-line "Requested n · available m" on the request page |
| "Technical Staff is suggested to reject the request" | `EquipmentRequestDetailView.test.js::suggests rejecting ...`, `::does not suggest rejecting when everything is covered` | `shortOnStock` hint in "Your decision" |
| "Rejecting requires an explanation" | `test_equipment_reject.py::test_a_reason_is_required`, `::test_a_very_long_reason_is_refused`, `EquipmentRequestDetailView.test.js::keeps Reject disabled until a reason is typed`, `test_equipment_reject_routes.py::test_a_missing_reason_is_a_400` | `reject_request` validation; Reject button disabled until the reason has text |
| "...that's sent to the Event Coordinator" | `test_equipment_reject.py::test_reject_marks_the_request_rejected_with_the_reason_and_who_decided`, `::test_reject_notifies_the_coordinator_of_the_decision`, `EquipmentBookingStatus.test.js::shows why a request was rejected` | reason stored on `equipment_requests`, shown in the coordinator's Equipment Booking section; `_notify_request_decision` is still a placeholder |
| (design) Only a pending request, Technical Support only | `test_authz_equipment_reject.py` (all), `test_equipment_reject_routes.py::test_an_already_decided_request_is_403`, `::test_a_coordinator_cannot_reject` | `rule_equipment_request_reject` |
| (design) Rejecting works on a cancelled event's pending request | `test_authz_equipment_reject.py::test_rejecting_does_not_depend_on_the_event_status`, `test_equipment_reject_routes.py::test_a_cancelled_events_pending_request_can_still_be_rejected` | no event-status check in the rule |
| (design) Never overwrites an accepted request | `test_equipment_reject.py::test_the_update_is_conditional_on_the_request_still_being_pending` | update conditioned on `status = 'pending'` |
| (design) Rejecting reserves/releases nothing | `test_equipment_reject.py::test_reject_reserves_nothing` | pending requests hold no stock |

## Sprint 3 — Update Quantity on an Existing Equipment Reservation (IS-43, Nawaz)

Source: the Reservation story's third sub-story. Unit tests:
`test_equipment_change.py` (service), `test_authz_equipment_change.py`
(rules), `test_equipment_change_routes.py` (routes). Frontend:
`EquipmentChangeRequests.test.js`, `EquipmentChangeDecisions.test.js`,
`EquipmentBookingStatus.test.js` ("quantity changes"),
`EquipmentRequestDetailView.test.js`, `EquipmentRequestsView.test.js`,
`equipment.test.js`. Needs migration
`20261019200000_equipment_change_requests.sql`. Not tested against a real
database.

| Criterion | Test | Implementation |
|---|---|---|
| "Coordinator's change request triggers a recalculation of available quantity for that date/time" | `test_equipment_change.py::test_an_increase_is_accommodated_when_enough_units_could_cover_the_request`, `::test_an_increase_is_not_accommodated_when_short_and_says_by_how_much`, `::test_a_decrease_is_always_accommodated`, `::test_pending_changes_carry_a_fresh_check_and_decided_ones_do_not`, `EquipmentChangeDecisions.test.js` (shows the recalculated availability) | `change_service._recalculate`, `list_changes_for_request` (check computed on every read) |
| The coordinator can ask for a change | `test_equipment_change.py::test_create_stores_the_ask_with_the_current_and_requested_quantity`, `::test_the_new_quantity_must_be_a_whole_number_of_at_least_one`, `::test_asking_for_the_quantity_it_already_has_is_refused`, `::test_a_second_ask_while_one_is_waiting_is_refused`, `EquipmentChangeRequests.test.js` | `POST /equipment/requests/<id>/change-requests`, `create_change_request`, `EquipmentChangeRequests.vue` |
| "If accommodated, the event record reflects the new reserved quantity" | `test_equipment_change.py::test_accepting_an_increase_reserves_the_extra_unit_and_updates_the_quantity`, `::test_the_extra_units_are_never_ones_the_request_already_holds`, `::test_accepting_a_decrease_releases_the_highest_asset_tags` | `accept_change`: reservation rows added or removed, line quantity updated (the event page reads these) |
| "If the new quantity can't be accommodated, Technical Staff rejects the change with an explanation to the Coordinator" | `test_equipment_change.py::test_an_increase_the_stock_cannot_cover_is_refused_and_changes_nothing`, `::test_reject_records_the_reason_and_leaves_the_reservation_alone`, `::test_rejecting_requires_a_reason`, `EquipmentChangeDecisions.test.js` (disabled Accept, suggestion, reason required), `EquipmentChangeRequests.test.js::shows why an ask was rejected` | `reject_change`; reason shown to the coordinator under the request |
| (design) Technical Support only decide; coordinator only asks for own confirmed request | `test_authz_equipment_change.py` (all), `test_equipment_change_routes.py` (403/404 cases) | `rule_equipment_change_*` |
| (design) Event must be live to accept; reject always allowed | `test_authz_equipment_change.py::test_accepting_needs_a_live_event_but_rejecting_does_not`, `test_equipment_change_routes.py::test_accept_is_blocked_on_a_cancelled_event_but_reject_is_not` | `CHANGEABLE_EVENT_STATUSES` |
| (design) Never double-applied or overwritten | `test_equipment_change.py::test_someone_deciding_it_first_releases_the_extra_unit`, `::test_rejecting_a_change_decided_a_moment_ago_does_not_overwrite_it`, `::test_the_unique_index_catching_a_simultaneous_ask_is_a_clear_error` | claim conditioned on `pending`; partial unique index |
| (design) Failure leaves nothing half-applied | `test_equipment_change.py::test_a_failure_updating_the_quantity_undoes_the_claim_and_the_reservation`, `::test_the_exclusion_constraint_refusing_the_extra_unit_is_a_clear_error` | undo steps in `accept_change` |
| Technical Support can find asks waiting | `EquipmentRequestsView.test.js`, `test_equipment_change_routes.py::test_technical_staff_see_the_pending_queue_and_a_coordinator_does_not` | `GET /equipment/change-requests`, "Quantity changes waiting" on the queue |

### IS-61 CRUD in Venue Catalogue

Story: "As a Venue staff, I want to add, edit and delete venues so that I can easily manage what venues ConnectSphere currently has." Built on the existing `venues` table; deleting is a soft delete (`deleted_at`). Ongoing events are those not completed, cancelled or rejected. Unit: `test_venue_catalogue_crud.py` (named by criterion, `test_ac1_*` ... `test_ac4_*`, plus `test_route_*`). Integration: `test_venue_catalogue_crud_integration.py`. Frontend: `lib/venueCatalogue.test.js`, `lib/venueBookings.test.js` (`unreplacedVenueReleases`), `VenueFormView.test.js`, `VenueDetailView.test.js`, `VenueRemovedAlert.test.js`, `VenueBookingStatus.test.js`.

| Criterion | Test | Implementation |
|---|---|---|
| Only Venue Staff add, edit or delete venues (others 403) | `test_venue_catalogue_crud.py::test_venue_staff_may_add_edit_and_delete_venues`, `::test_no_other_role_may_add_edit_or_delete_venues`, `::test_route_only_venue_staff_add_edit_or_delete`, `VenueDetailView.test.js` (no staff actions for coordinators) | `rules.py::rule_venue_create` / `rule_venue_edit` / `rule_venue_delete`, `app/venues/routes.py`, `roles.js` (`venue-create`, `venue-edit`) |
| AC1: Venue Staff can add a venue | `::test_ac1_*`, `::test_route_ac1_*`, `test_venue_catalogue_crud_integration.py::test_ac1_*`, `VenueFormView.test.js` (add), `venueCatalogue.test.js` (`validateVenueForm`, `venuePayload`) | `POST /venues`, `venue_service.py::create_venue`, `VenueFormView.vue` (`/venues/new`, always added as available) |
| AC2: Venue Staff can edit a venue's details | `::test_ac2_*`, `::test_route_ac2_*`, `test_venue_catalogue_crud_integration.py::test_ac2_*`, `VenueFormView.test.js` (edit), `venueCatalogue.test.js` (`changedFields`) | `POST /venues/<id>`, `venue_service.py::update_venue`, `VenueFormView.vue` (`/venues/:id/edit`), constraint `venues_buffers_non_negative` |
| AC3: Venue Staff can delete a venue; it leaves the catalogue but old bookings can still show it | `::test_ac3_*`, `::test_route_ac3_*`, `test_venue_catalogue_crud_integration.py::test_ac3_*`, `VenueDetailView.test.js` (delete) | `DELETE /venues/<id>`, `venue_service.py::delete_venue` / `list_venues` / `get_venue`, function `delete_venue()` |
| AC4: ongoing events that booked the venue lose their booking (finished events keep theirs; other venues' bookings untouched) | `::test_ac4_released_bookings_are_reported`, `test_venue_catalogue_crud_integration.py::test_ac4_an_ongoing_events_booking_is_released_and_logged`, `::test_ac4_bookings_of_finished_events_are_left_alone`, `::test_ac4_other_venues_bookings_for_the_session_are_untouched`, `::test_ac4_a_coordinators_own_cancellation_is_not_marked_as_a_release` | function `delete_venue()`, `venue_bookings.released_by_venue_deletion`, `venue_booking_status_log` |
| AC4: a confirmed session returns to planning (and one under a safety check, with its pending check withdrawn), so the coordinator can book again | `::test_ac4_a_confirmed_session_goes_back_to_planning_so_it_can_be_rebooked`, `::test_ac4_a_session_under_safety_check_*`, `::test_ac4_withdrawing_*`, `test_venue_catalogue_crud_integration.py::test_ac4_a_confirmed_event_returns_to_planning`, `::test_ac4_a_session_under_safety_check_has_it_withdrawn_and_returns_to_planning`, `::test_ac4_the_coordinator_can_book_another_venue_afterwards` | `venue_service.py::delete_venue` (via `transitions.transition`), `safety_service.py::withdraw_pending_review` |
| AC4: the coordinator is alerted on the event details page to book another venue | `VenueRemovedAlert.test.js`, `venueBookings.test.js` (`unreplacedVenueReleases`), `VenueBookingStatus.test.js` (IS-61 marker) | `VenueRemovedAlert.vue` (top of `EventDetailsView.vue`, coordinator view), `lib/venueBookings.js::unreplacedVenueReleases`, `VenueBookingStatus.vue` |
| A deleted venue can't be booked or approved against, even racing the delete | `::test_a_deleted_venue_cannot_be_requested`, `::test_a_booking_racing_the_delete_gets_the_databases_message`, `test_venue_catalogue_crud_integration.py::test_a_deleted_venue_cannot_be_requested`, `::test_the_database_refuses_a_booking_on_a_deleted_venue_written_straight_to_the_table`, `::test_a_pending_booking_left_on_a_deleted_venue_cannot_be_approved` | `booking_service.py::_get_venue` / `create_booking_request` / `_decide_booking`, trigger `trg_venue_bookings_refuse_deleted_venue` |
