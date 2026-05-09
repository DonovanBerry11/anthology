// Anthology — Supabase configuration
// ─────────────────────────────────────────────────────────────────────────────
// SITE_URL is the single source of truth for the production domain.
// To change domain in future: update SITE_URL below, then update two fields in
// Supabase dashboard → Authentication → URL Configuration:
//   • Site URL
//   • Redirect URLs (add the new /auth/callback.html URL)
// ─────────────────────────────────────────────────────────────────────────────

const SITE_URL    = 'https://anthology-weld.vercel.app'
const SUPABASE_URL = 'https://uzjkepauhgbuunvcokru.supabase.co'
const SUPABASE_KEY = 'sb_publishable_eBmXtZ0QxVcdethdAy2NSg_-izzQaoJ'

// supabase global is provided by the CDN <script> loaded before this file
const _supabase = supabase.createClient(SUPABASE_URL, SUPABASE_KEY, {
  auth: {
    flowType: 'pkce',
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: true
  }
})

// Utility: redirect to login if no active session
async function requireAuth() {
  const { data: { session } } = await _supabase.auth.getSession()
  if (!session) window.location.href = SITE_URL + '/login.html'
  return session
}

// Utility: update nav auth link based on session state
async function updateAuthNav() {
  const { data: { session } } = await _supabase.auth.getSession()
  const link = document.getElementById('auth-nav-link')
  if (!link) return
  if (session) {
    link.textContent = 'Account'
    link.href = '/account.html'
  } else {
    link.textContent = 'Sign in'
    link.href = '/login.html'
  }
}
