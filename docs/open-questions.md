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
  as one Dashboard route for every role after login, whose own content
  (which nav links it shows) adapts by role — see
  `frontend/src/lib/roles.js`'s module docstring for the reasoning. This
  still holds now that Events/Create Event/Event Details are real pages
  (Aaralyn's IS-3/IS-4 work), not placeholders: the dashboard is a
  landing page users are routed to after login, not itself the
  role-specific view — reaching the create-event form or an event's
  detail page is normal in-app navigation from there, no different from
  clicking into Venues once that's built. Please confirm this reading is
  acceptable, or whether separate landing pages per role are expected
  straight after login instead.

- **Which roles reach which sections (IS-27).** `frontend/src/lib/
  roles.js`'s `ROUTE_ACCESS` table (the single source both the dashboard
  nav and the router's role gate read from) allows: Events and Create
  Event to event_organizer/event_coordinator and event_organizer only
  respectively (Event Request Creation is organiser-only per its own
  story); Venues to event_coordinator/venue_staff (quoting the Week 4
  instructions' Venue Catalogue description); Reassign Coordinator and
  an event's own detail page to event_coordinator (plus event_organizer
  for the detail page, since an organiser can view/edit their own
  event). This mapping isn't specified anywhere in the stories — it's
  inferred per-route from which story or authz rule owns that feature.
  attendee and technical_support_staff currently unlock nothing on the
  dashboard (see `docs/traceability.md`'s "Explicitly deferred" —
  nothing built for those roles yet this sprint). Please confirm this
  mapping, especially whether Attendee/Technical Support Staff should
  see something else instead of the current fallback message.
