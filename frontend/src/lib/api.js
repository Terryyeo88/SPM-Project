/**
 * Thin fetch wrapper for the Flask backend. Attaches the current
 * Supabase session's access token as a Bearer header on every request --
 * this is what app/auth/context.py on the backend actually reads.
 */
import { supabase } from './supabaseClient'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:5000'

async function authHeaders() {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(await authHeaders()),
    ...(options.headers || {}),
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    // Backend error shape: {"error": {"code": "...", "message": "..."}}
    // -- see backend/app/shared/errors.py.
    const message = body?.error?.message || `Request failed with status ${response.status}`
    const error = new Error(message)
    error.status = response.status
    error.code = body?.error?.code
    throw error
  }

  return body
}

export const apiGet = (path) => request(path, { method: 'GET' })
export const apiPost = (path, data) => request(path, { method: 'POST', body: JSON.stringify(data) })
