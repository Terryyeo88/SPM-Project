# Traceability: acceptance criterion → test → source

Maps each IS-1 (User Authorisation and Authentication) acceptance criterion
or story clarification to the test that proves it and the file that
implements it. Created in Phase 4; covers Phase 3 (authentication) and
Phase 4 (authorisation policy) together since both are IS-1.

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
| `_get_last_active` / `_touch_session_activity` behave correctly against the REAL `session_activity` table (caught a real `.maybe_single()` null-handling bug unit tests structurally couldn't) | `test_session_activity_integration.py::*` (marked `integration`) | `app/auth/context.py` |

## Phase 4 — authorisation policy

| Criterion / source | Test | Implementation |
|---|---|---|
| "An organiser sees full details of their own events; other organisers' events are hidden" (ruled: 404, not a partial view) | `test_authz_policy.py::test_organiser_denied_on_another_organisers_event`, `::test_organiser_allowed_on_own_event` | `app/authz/rules.py::rule_event_view` |
| Prerequisite: an assigned coordinator can view the event they're assigned to | `test_authz_policy.py::test_coordinator_allowed_view_on_assigned_event` | `app/authz/rules.py::rule_event_view` |
| "An organiser cannot edit directly after submission; changes go via the coordinator" | `test_authz_policy.py::test_organiser_denied_edit_after_submission`, `::test_organiser_allowed_edit_while_draft` | `app/authz/rules.py::rule_event_edit` |
| "A coordinator acts only on events assigned to them" (approve) + Event Status Management workflow | `test_authz_policy.py::test_coordinator_denied_approve_on_event_assigned_to_someone_else`, `::test_coordinator_denied_approve_from_status_other_than_under_review`, `::test_coordinator_allowed_approve_on_own_assigned_event_under_review` | `app/authz/rules.py::rule_event_approve` |
| Same, for reject | `test_authz_policy.py::test_coordinator_denied_reject_on_event_assigned_to_someone_else`, `::test_coordinator_allowed_reject_on_own_assigned_event_under_review` | `app/authz/rules.py::rule_event_reject` |
| Event Review and Approval story: "Request Clarification", coordinator-only, status stays `under_review` | `test_authz_policy.py::test_coordinator_allowed_request_clarification_under_review`, `::test_coordinator_denied_request_clarification_on_unassigned_event` | `app/authz/rules.py::rule_event_request_clarification` |
| Cancelled Status story: "Coordinator can change status to cancelled after approval of the event request" | `test_authz_policy.py::test_coordinator_denied_cancel_before_approval`, `::test_coordinator_allowed_cancel_post_approval_on_own_event`, `::test_coordinator_denied_cancel_on_event_assigned_to_someone_else` | `app/authz/rules.py::rule_event_cancel` (status set is an inference — flagged in the Phase 4 report and in the rule's own comment) |
| "A user's access is limited to their role" — only an Event Organizer creates an event request | `test_authz_policy.py::test_attendee_denied_event_create_role_only_no_resource`, `::test_organiser_allowed_event_create` | `app/authz/rules.py::rule_event_create` |
| View Event Requests story: organiser can list their own drafted/created requests | `test_authz_policy.py::test_event_list_denied_for_role_with_no_listing_rights`, `::test_organiser_allowed_event_list` | `app/authz/rules.py::rule_event_list` |
| Event Status Management story: submitting changes status to Submitted, organiser-only, from draft only | `test_authz_policy.py::test_organiser_denied_event_submit_on_event_that_isnt_theirs`, `::test_organiser_denied_event_submit_from_status_other_than_draft`, `::test_organiser_allowed_event_submit_from_draft` | `app/authz/rules.py::rule_event_submit` |
| Readied for Justin's `coordinator_service.py::reassign_coordinator` (not wired by this ticket) | `test_authz_policy.py::test_coordinator_allowed_reassign_when_currently_assigned`, `::test_coordinator_denied_reassign_when_not_currently_assigned` | `app/authz/rules.py::rule_event_reassign_coordinator` |
| "An attendee cannot [do] internal actions" | `test_authz_policy.py::test_attendee_denied_every_internal_action` | all `rule_event_*` functions (deny via role/relationship check) |
| Customer requirement: a user with multiple roles gets the union of their permissions | `test_authz_policy.py::test_multi_role_user_gets_union_of_permissions` | `app/authz/rules.py` (structural: `role in user.roles`, never a single-role assumption) |
| Deny by default: an unknown action string is never allowed | `test_authz_policy.py::test_unknown_action_denied` | `app/authz/policy.py::_decide` |
| Deny by default: a real action with no rule wired up is never allowed | `test_authz_policy.py::test_registered_action_with_no_rule_denied` | `app/authz/policy.py::_decide` |
| 403-vs-404 selection: relationship exists but a condition blocks the action → 403 | `test_authz_policy.py::test_403_not_404_when_relationship_exists_but_status_blocks` | `app/authz/policy.py::authorise`, `docs/design-decisions.md` §403 vs 404 |
| 403-vs-404 selection: no relationship at all → 404 | `test_authz_policy.py::test_404_not_403_when_no_relationship_exists` | same |

## Explicitly deferred (not tested because not built)

- Registration-related criteria ("an attendee cannot view another attendee's
  registration") — no `registrations` table or attendee-event linkage
  exists in the schema yet. No action, no rule, no test.
- Field-level visibility ("an attendee sees no internal planning
  information") — a serialisation concern, not a `can()` decision; deferred
  to whoever builds the event routes/serialisers. See
  `docs/design-decisions.md`.
