# Open questions

Things IS-1 decided and implemented, but that should still get explicit
customer confirmation rather than staying as our best reading of the
stories. Not implementation gaps — each of these has a decision already
made and recorded in `docs/design-decisions.md`; this file is the list of
decisions worth double-checking.

- **event.cancel's status range.** The Cancelled Status story says
  "after approval of the event request". We implemented that as the range
  `approved, planning, confirmed` (excluding `completed`), reasoning that
  the story's own scenario (coordinator can't secure a venue/equipment)
  happens during planning, not at the instant of approval — see
  `docs/design-decisions.md` §event.cancel. Please confirm "after approval"
  was meant as that range and not literally the single status `approved`.

- **Venue "availability" is a manual status, not a real calendar.** The
  View Venue Catalogue story's acceptance criterion ("the availability of
  the venue tells the Event Coordinator when the venue is occupied and
  when it is available") reads like it wants an actual occupied/free
  calendar. That calendar is a separate story (Venue Availability
  Calendar), driven by real bookings — and the booking tables it would
  read from (Venue Booking Request/Approval) are explicitly out of scope
  for Sprint 1. Until those exist, `venues.status` is a single
  manually-set flag (`available` / `occupied` / `maintenance`) per venue,
  not derived from any booking data — see
  `supabase/migrations/20260923000000_venues.sql`'s own comments. Please
  confirm this reading is right, and that a real calendar is expected
  once bookings exist rather than this flag being the intended final
  behaviour.

- **Venue Staff granted the same catalogue access as Event Coordinator.**
  The View Venue Catalogue story is written only for the Event
  Coordinator role. We additionally granted `venue_staff` the same
  `venue.view`/`venue.list` access (see `rule_venue_list` in
  `app/authz/rules.py`), reasoning that Venue Staff need to see the same
  venue details when they later approve or reject bookings against these
  records (Venue Booking Approval story). This is our own inference, not
  a line from the story text — please confirm Venue Staff should have
  this access.
