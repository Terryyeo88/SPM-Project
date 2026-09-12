/**
 * Shared Supabase client for the frontend. Uses the PUBLISHABLE key only
 * (safe to ship to the browser -- it only works within whatever Row
 * Level Security policies exist on each table). Never put the secret
 * key anywhere in frontend code.
 */
import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error(
    'Missing VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY. Copy .env.example to .env ' +
      'in frontend/ and fill in your project values (Supabase dashboard -> ' +
      'Project Settings -> API Keys -- use the publishable key here, not the secret one).',
  )
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
