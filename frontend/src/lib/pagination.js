/**
 * Client-side paging over a list already loaded in full -- e.g. an event
 * request's Change History (components/EventLogHistory.vue), which is small
 * enough to fetch at once but long enough to want splitting up. Pure, so it
 * can be unit-tested without mounting anything.
 */

/**
 * One page of `items`:
 *   { items, page, pageCount, total, from, to }
 * `page` is 1-based and clamped into range (an empty list is page 1 of 1),
 * so a list that shrank under the current page still shows its last page.
 * `from`/`to` are the 1-based positions shown ("6–10 of 12"); 0 when empty.
 */
export function paginate(items, page, pageSize) {
  const list = Array.isArray(items) ? items : []
  const size = Math.max(1, Math.floor(pageSize) || 1)
  const pageCount = Math.max(1, Math.ceil(list.length / size))
  const current = Math.min(Math.max(1, Math.floor(page) || 1), pageCount)
  const start = (current - 1) * size
  const shown = list.slice(start, start + size)
  return {
    items: shown,
    page: current,
    pageCount,
    total: list.length,
    from: shown.length ? start + 1 : 0,
    to: start + shown.length,
  }
}
