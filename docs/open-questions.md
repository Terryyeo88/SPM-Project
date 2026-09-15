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

- **"Routed to a view appropriate to their role" (IS-27).** Implemented
  as one Dashboard route for every role, whose own content (which nav
  links it shows) adapts by role, rather than separate pages per role —
  see `frontend/src/lib/roles.js`'s module docstring for the reasoning
  (mainly: Events/Venues are still placeholders owned by Aaralyn's and
  Nawaz's stories, so a per-role route here would mean guessing at pages
  that are someone else's to design). Please confirm this reading is
  acceptable, or whether separate pages per role are expected instead.

- **Which roles see which nav sections (IS-27).** `frontend/src/lib/
  roles.js`'s `NAV_LINKS` gates Events to event_organizer/
  event_coordinator, Venues to event_coordinator/venue_staff (quoting the
  Week 4 instructions' Venue Catalogue description), and Reassign
  Coordinator to event_coordinator only. This mapping isn't specified
  anywhere in the stories — it's inferred per-link from which story or
  authz rule owns that feature. attendee and technical_support_staff
  currently unlock nothing (see `docs/traceability.md`'s "Explicitly
  deferred" — nothing built for those roles yet this sprint). Please
  confirm this mapping, especially whether Attendee/Technical Support
  Staff should see something else instead of the current fallback
  message.
