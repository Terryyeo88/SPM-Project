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
| Readied for Justin's `coordinator_service.py::reassign_coordinator` (not wired by this ticket) | `test_authz_policy.py::test_coordinator_allowed_reassign_when_currently_assigned`, `::test_coordinator_denied_reassign_when_not_currently_assigned` | `app/authz/rules.py::rule_event_reassign_coordinator` |
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
| End-to-end against a real database (migration actually applies, buffers/conflict/rejection round-trip for real) | `test_venue_bookings_integration.py` (all cases) | `supabase/migrations/20261004000000_venue_bookings.sql`, `app/venues/booking_service.py` |
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

## Explicitly deferred (not tested because not built)

- Registration-related criteria ("an attendee cannot view another attendee's
  registration") — no `registrations` table or attendee-event linkage
  exists in the schema yet. No action, no rule, no test.
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
