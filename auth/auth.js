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

// Utility: update nav auth link based on session state.
// Call with a session object (from onAuthStateChange) for instant update,
// or with no argument to fall back to getSession().
async function updateAuthNav(session) {
  const link = document.getElementById('auth-nav-link')
  if (!link) return
  if (session === undefined) {
    const { data } = await _supabase.auth.getSession()
    session = data.session
  }
  link.textContent = session ? 'Account' : 'Sign in'
  link.href = session ? '/account.html' : '/login.html'
}
