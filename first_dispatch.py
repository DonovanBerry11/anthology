#!/usr/bin/env python3
"""
first_dispatch.py — Generates and publishes a combined 5-section dispatch
plus 5 companion notes for a new user immediately after bootstrap completes.

Runs on the server only (/root/pipeline/). Called by bootstrap_server.py via
subprocess.Popen (non-blocking) after /first-dispatch is hit.

Output per run:
  • 1 combined dispatch HTML page containing 5 demarcated sections
  • 5 note HTML pages, one per dispatch topic
  • Each section in the combined dispatch links to its corresponding note

Usage:
    python3 /root/pipeline/first_dispatch.py \
        --user-id <supabase-uuid> \
        --env /root/.anthology.env
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# ── Constants ─────────────────────────────────────────────────────────────────

VENV_PYTHON = '/root/anthology-env/bin/python3'
MODEL       = 'claude-sonnet-4-6'
N_DISPATCHES = 5
ROMAN_LABELS = ['I.', 'II.', 'III.', 'IV.', 'V.']

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_env_file(path: str) -> dict:
    """Parse a simple KEY=VALUE .env file into a dict."""
    env = {}
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env


def extract_text(response) -> str:
    """Concatenate all text blocks from an Anthropic message response."""
    parts = []
    for block in response.content:
        if hasattr(block, 'text') and block.text:
            parts.append(block.text)
    return '\n'.join(parts).strip()


def run_cmd(cmd, timeout: int = 180) -> str:
    """
    Run cmd (list → execvp, str → shell). Raise RuntimeError on non-zero exit.
    Returns stdout stripped.
    """
    result = subprocess.run(
        cmd,
        shell=isinstance(cmd, str),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed (rc={result.returncode}):\n{result.stderr}"
        )
    return result.stdout.strip()


def safe_slug(text: str, fallback: str = 'dispatch') -> str:
    """Convert free text to a URL-safe kebab-case slug."""
    slug = text.lower()
    slug = re.sub(r'[^a-z0-9-]', '-', slug)
    slug = re.sub(r'-+', '-', slug).strip('-')
    return slug or fallback


def parse_json_response(text: str, context: str = '') -> list | dict | None:
    """
    Extract the first valid JSON object or array from text.
    Tolerant of markdown fences and surrounding commentary.
    """
    # Remove markdown fences if present
    cleaned = re.sub(r'```(?:json)?\s*', '', text)
    cleaned = re.sub(r'```', '', cleaned)
    # Try to find JSON array first, then object
    for pattern in [r'\[.*\]', r'\{.*\}']:
        m = re.search(pattern, cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                continue
    logging.warning(f'Could not parse JSON{" in " + context if context else ""}')
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Generate and publish a first combined dispatch (5 sections + 5 notes) '
                    'for a new user'
    )
    parser.add_argument('--user-id', required=True, help='Supabase UUID')
    parser.add_argument(
        '--env', default='/root/.anthology.env',
        help='Path to credentials env file'
    )
    args = parser.parse_args()

    user_id  = args.user_id.strip()
    env_file = args.env

    # ── Load credentials ───────────────────────────────────────────────────────
    load_dotenv(env_file)
    file_env = load_env_file(env_file)

    api_key       = file_env.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_API_KEY', '')
    system_dir    = Path(file_env.get('SYSTEM_DIR',    '/root/anthology-system'))
    anthology_dir = Path(file_env.get('ANTHOLOGY_DIR', '/root/anthology'))

    if not api_key:
        print('ERROR: ANTHROPIC_API_KEY not set in env file', file=sys.stderr)
        sys.exit(1)

    # ── Logging ────────────────────────────────────────────────────────────────
    est   = timezone(timedelta(hours=-5))
    today = datetime.now(est).strftime('%Y-%m-%d')
    log_file = system_dir / 'logs' / f'first-dispatch-{today}.md'
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler(str(log_file)),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger('first-dispatch')
    logger.info(f'Starting first combined dispatch for user_id={user_id}')

    # ── Read orientation file ──────────────────────────────────────────────────
    registry_path = system_dir / 'users' / 'registry.json'
    if not registry_path.exists():
        logger.error(f'Registry not found: {registry_path}')
        sys.exit(1)

    registry   = json.loads(registry_path.read_text(encoding='utf-8'))
    user_entry = next(
        (u for u in registry.get('users', []) if u['user_id'] == user_id),
        None,
    )
    if not user_entry:
        logger.error(f'User {user_id} not found in registry.json')
        sys.exit(1)

    orientation_path = Path(user_entry['orientation_path'])
    if not orientation_path.exists():
        logger.error(f'Orientation file not found: {orientation_path}')
        sys.exit(1)

    # First ~2500 chars covers Stated Preferences and profile
    orientation_excerpt = orientation_path.read_text(encoding='utf-8')[:2500]
    logger.info(f'Loaded orientation: {orientation_path}')

    # ── Read voice.md if present ───────────────────────────────────────────────
    voice_instruction_block = ''
    voice_path = orientation_path.parent / 'voice.md'
    if voice_path.exists():
        voice_text = voice_path.read_text(encoding='utf-8')
        logger.info(f'Loaded voice.md: {voice_path}')
        # Extract populated fields (state != unknown and != default)
        populated_lines = []
        current_section = ''
        for line in voice_text.splitlines():
            stripped = line.strip()
            # Track section headings (## 1. Register etc.)
            if stripped.startswith('## ') and stripped[3:4].isdigit():
                current_section = stripped.lstrip('#').strip()
            # Capture lines after "> " that are not "unknown" or "default"
            if stripped.startswith('> ') and current_section:
                value = stripped[2:].strip()
                if value and value.lower() not in ('unknown', 'default'):
                    populated_lines.append(f'- {current_section}: {value}')
        if populated_lines:
            voice_instruction_block = (
                '\n\nThe following voice preferences apply to this user. '
                'Apply them to each dispatch section:\n'
                + '\n'.join(populated_lines)
                + '\nDo not apply preferences marked unknown or default.'
            )
            logger.info(
                f'Voice instruction block built: {len(populated_lines)} populated fields'
            )
        else:
            logger.info('voice.md exists but all fields are unknown/default — not injecting')
    else:
        logger.info(f'No voice.md found at {voice_path} — proceeding without voice calibration')

    # ── Next dispatch/note numbers ─────────────────────────────────────────────
    pieces_dispatches_dir = system_dir / 'pieces' / 'dispatches'
    pieces_notes_dir      = system_dir / 'pieces' / 'notes'
    pieces_dispatches_dir.mkdir(parents=True, exist_ok=True)
    pieces_notes_dir.mkdir(parents=True, exist_ok=True)

    def next_piece_number(pieces_dir: Path, prefix: str) -> int:
        nums = [
            int(m.group(1))
            for d in pieces_dir.iterdir()
            if d.is_dir()
            for m in [re.match(rf'{re.escape(prefix)}(\d+)', d.name)]
            if m
        ]
        return max(nums, default=0) + 1

    next_dispatch_num = next_piece_number(pieces_dispatches_dir, 'd')
    next_note_num     = next_piece_number(pieces_notes_dir, 'n')
    logger.info(f'Next dispatch number: {next_dispatch_num}, next note number: {next_note_num}')

    # ── Anthropic client ────────────────────────────────────────────────────────
    client = anthropic.Anthropic(api_key=api_key)

    # ── Step 1: Find 5 topics via web search ───────────────────────────────────
    logger.info('Step 1: Finding 5 topics with web search…')

    topics_prompt = f"""You are the editorial agent for Anthology, a personalised newspaper. \
A new reader has just completed onboarding. You need to find 5 current news stories to anchor \
their first edition.

READER PROFILE (from their orientation file):
{orientation_excerpt}{voice_instruction_block}

Search the web for 5 current news stories from the past 48 hours that would genuinely interest \
this reader. Choose stories from different domains (e.g. politics, economics, geopolitics, \
technology, finance) so the edition covers a range. Each story should be substantive — \
a development that rewards analysis. Avoid soft news or celebrity items.

After searching, respond with ONLY a valid JSON array of exactly 5 objects. \
No markdown fences, no commentary — just the JSON:
[
  {{
    "headline": "The actual news headline",
    "summary": "2–3 sentences summarising what happened and its immediate significance",
    "source": "Publication or news outlet name",
    "why_relevant": "One sentence on why this story fits this reader's specific interests",
    "suggested_slug": "kebab-case-slug-max-5-words",
    "suggested_title": "An analytical dispatch title (not the headline — frames the story analytically)",
    "note_slug": "kebab-case-slug-for-the-companion-note-max-5-words"
  }},
  …
]"""

    topics_response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 8,
        }],
        messages=[{"role": "user", "content": topics_prompt}],
    )

    topics_text = extract_text(topics_response)
    logger.info(f'Topics response (first 400 chars): {topics_text[:400]}')

    topics = parse_json_response(topics_text, 'topics response')
    if not topics or not isinstance(topics, list) or len(topics) < N_DISPATCHES:
        logger.error(f'Could not parse 5 topics. Full response:\n{topics_text}')
        sys.exit(1)

    topics = topics[:N_DISPATCHES]
    for t in topics:
        t['slug']      = safe_slug(t.get('suggested_slug', ''), 'dispatch')
        t['title']     = (t.get('suggested_title') or t.get('headline') or 'Dispatch').strip()
        t['note_slug'] = safe_slug(t.get('note_slug', t['slug'] + '-note'), 'note')

    logger.info(f'Topics selected: {[t["title"] for t in topics]}')

    # ── Step 2: Draft all 5 dispatch bodies in one call ────────────────────────
    logger.info('Step 2: Drafting 5 dispatch bodies…')

    topics_summary = '\n'.join(
        f'{i+1}. TITLE: {t["title"]}\n   Headline: {t["headline"]}\n'
        f'   Summary: {t["summary"]}\n   Source: {t["source"]}\n'
        f'   Why relevant: {t["why_relevant"]}'
        for i, t in enumerate(topics)
    )

    dispatch_draft_prompt = f"""You are the writer for Anthology, a personalised newspaper. \
Write 5 dispatch sections for the reader described below. These sections appear in a combined \
dispatch; each links to a companion note where deeper analysis lives.

READER PROFILE:
{orientation_excerpt}{voice_instruction_block}

FIVE STORIES TO COVER:
{topics_summary}

For each story, write a separate dispatch section body. Each dispatch section must:
- Be no more than 150 words — this is a hard cap. Count carefully.
- Report what happened. Do not editorialize, characterise, or use rhetorical framing. \
Save analysis and opinion for the companion note.
- Use prose paragraphs only — no subheadings, no bullet points, no numbered lists
- Open with a strong declarative sentence (not a question, not "In recent weeks")
- Close with a forward-looking sentence about what to watch
- NOT include the title, byline, date, or any meta-text — body paragraphs only
- Be calibrated to this reader's background and sophistication
- Do not name news outlets in the prose. Embed the substance of what they reported as a \
direct statement, and attach a hyperlink to the specific claim or data point. \
Correct form: '[the vote was 8–4](url)'. Incorrect form: 'As CNBC reported, the vote was 8–4'.

Respond with ONLY a valid JSON array of exactly 5 objects. No markdown fences:
[
  {{
    "index": 0,
    "body": "Full dispatch section body text for story 1…"
  }},
  …
]"""

    dispatch_draft_response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": dispatch_draft_prompt}],
    )

    drafts_data = parse_json_response(extract_text(dispatch_draft_response), 'dispatch drafts')
    if not drafts_data or not isinstance(drafts_data, list) or len(drafts_data) < N_DISPATCHES:
        logger.error('Could not parse dispatch drafts JSON')
        sys.exit(1)

    # Index the drafts by their index field
    drafts_by_idx = {d.get('index', i): d.get('body', '') for i, d in enumerate(drafts_data)}
    dispatch_bodies = [drafts_by_idx.get(i, '').strip() for i in range(N_DISPATCHES)]

    word_counts = [len(b.split()) for b in dispatch_bodies]
    logger.info(f'Dispatch drafts complete. Word counts: {word_counts}')

    # ── Step 3: QC pass on all 5 dispatches ───────────────────────────────────
    logger.info('Step 3: Quality check on 5 dispatches…')

    dispatches_for_qc = '\n\n'.join(
        f'=== DISPATCH {i+1}: {topics[i]["title"]} ===\n{body}'
        for i, body in enumerate(dispatch_bodies)
    )

    qc_prompt = f"""You are a quality editor for Anthology. Review these 5 dispatch sections.

Before checking anything else, independently verify specific factual claims in each section \
via web search — particularly named vote counts or margins, named scores or standings, \
named statistics, and current officeholders. Then for each section check:
1. STRUCTURE: Prose paragraphs only — no subheadings, bullets, or lists?
2. LENGTH: No more than 150 words? Flag and trim any section that exceeds this hard cap.
3. REGISTER: Plain reporting only — no editorialising, no rhetorical framing, no \
characterisation beyond what is directly attributable?
4. CITATION STYLE: No verbal outlet citation — "As X reported", "According to X", \
"X's coverage noted" are prohibited; sources must appear as inline hyperlinks on the claim.
5. OPENING: Strong declarative opening (not a question, not "In recent weeks")?
6. CLOSING: Forward-looking final sentence?
7. FACTUAL ACCURACY: Any claim contradicted by your web search must be corrected or removed.

For each dispatch that passes all checks, respond with just its index and PASS.
For each dispatch that needs fixing, respond with its index, REVISED, and the corrected body.

Format your response as a JSON array:
[
  {{"index": 0, "result": "PASS"}},
  {{"index": 1, "result": "REVISED", "body": "corrected full body text…"}},
  …
]

DISPATCHES TO REVIEW:
{dispatches_for_qc}"""

    qc_response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": qc_prompt}],
    )

    qc_data = parse_json_response(extract_text(qc_response), 'QC response')
    if qc_data and isinstance(qc_data, list):
        for qc_item in qc_data:
            idx = qc_item.get('index')
            if idx is not None and qc_item.get('result', '').upper().startswith('REVISED'):
                revised = qc_item.get('body', '').strip()
                if revised and len(revised.split()) >= 200:
                    dispatch_bodies[idx] = revised
                    logger.info(f'Dispatch {idx+1}: QC revised ({len(revised.split())} words)')
                else:
                    logger.warning(f'Dispatch {idx+1}: QC REVISED body too short, keeping original')
            else:
                logger.info(f'Dispatch {idx+1 if idx is not None else "?"}: QC PASS')
    else:
        logger.warning('Could not parse QC response — keeping original drafts')

    # ── Step 4: Draft all 5 note bodies in one call ────────────────────────────
    logger.info('Step 4: Drafting 5 companion notes…')

    dispatches_summary_for_notes = '\n'.join(
        f'{i+1}. TITLE: {topics[i]["title"]}\n'
        f'   Story: {topics[i]["summary"]}\n'
        f'   Dispatch excerpt (first 200 chars): {dispatch_bodies[i][:200]}…'
        for i in range(N_DISPATCHES)
    )

    note_draft_prompt = f"""You are a writer for Anthology, a personalised newspaper. \
You have just written 5 short dispatch sections (≤150 words each) covering current stories. \
Now write 5 companion notes — one for each story — that go deeper. Notes are where analysis, \
context, and opinion live; the dispatch section reported the facts, the note develops them.

READER PROFILE:
{orientation_excerpt}{voice_instruction_block}

STORIES (with dispatch summaries):
{dispatches_summary_for_notes}

Each companion note must:
- Be 400–600 words
- Take the story further: provide structural context, historical background, \
  stakeholder analysis, or an analytical angle the short dispatch could not develop
- Use prose paragraphs — no subheadings or bullet points
- Be written for this reader specifically — calibrated to their sophistication and interests
- NOT be a summary or repeat of the dispatch — the reader has already read the dispatch
- NOT include a title, byline, date, or meta-text — body paragraphs only
- Do not name news outlets in the prose. Embed the substance of what they reported as a \
  direct statement, and attach a hyperlink to the specific claim or data point. \
  Correct form: '[analysts projected 2.1% contraction](url)'. \
  Incorrect form: 'As the FT reported, analysts projected a 2.1% contraction'.

Respond with ONLY a valid JSON array of exactly 5 objects. No markdown fences:
[
  {{
    "index": 0,
    "body": "Full note body for story 1…"
  }},
  …
]"""

    note_draft_response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": note_draft_prompt}],
    )

    notes_data = parse_json_response(extract_text(note_draft_response), 'note drafts')
    if not notes_data or not isinstance(notes_data, list) or len(notes_data) < N_DISPATCHES:
        logger.error('Could not parse note drafts JSON')
        sys.exit(1)

    notes_by_idx = {n.get('index', i): n.get('body', '') for i, n in enumerate(notes_data)}
    note_bodies = [notes_by_idx.get(i, '').strip() for i in range(N_DISPATCHES)]

    note_word_counts = [len(b.split()) for b in note_bodies]
    logger.info(f'Note drafts complete. Word counts: {note_word_counts}')

    # ── Date strings ───────────────────────────────────────────────────────────
    now_est      = datetime.now(est)
    date_display = now_est.strftime('%B %Y')      # e.g. "May 2026"
    date_iso     = now_est.strftime('%Y-%m-%d')
    now_utc      = datetime.utcnow()

    token_file     = anthology_dir / '.publish-config'
    publish_note   = anthology_dir / 'publish_note.py'
    publish_disp   = anthology_dir / 'publish_dispatch.py'

    # ── Step 5: Write piece directories and publish notes ─────────────────────
    logger.info('Step 5: Publishing 5 companion notes…')

    note_urls = []  # per-user URLs, built as each note is published

    for i in range(N_DISPATCHES):
        note_num  = next_note_num + i
        note_slug = topics[i]['note_slug']
        note_title = f"{topics[i]['title']} — Further Reading"

        # Build standfirst from dispatch summary
        raw_sf = topics[i].get('summary', topics[i]['title'])[:200].strip()
        if raw_sf and raw_sf[-1] not in '.!?':
            raw_sf += '.'
        note_standfirst = raw_sf

        # Write piece directory
        note_dir = pieces_notes_dir / f'n{note_num:03d}-{note_slug}'
        note_dir.mkdir(parents=True, exist_ok=True)
        (note_dir / 'analysis.md').write_text(note_bodies[i], encoding='utf-8')
        (note_dir / 'log.md').write_text(
            f"# n{note_num:03d} — {note_title}\n\n"
            f"**Generated:** {now_utc.isoformat()}Z UTC\n"
            f"**User ID:** {user_id}\n"
            f"**Trigger:** first-dispatch companion note {i+1}/5\n"
            f"**Model:** {MODEL}\n"
            f"**Dispatch slug:** {topics[i]['slug']}\n"
            f"**Word count:** {len(note_bodies[i].split())}\n",
            encoding='utf-8',
        )

        logger.info(f'  Publishing note {i+1}/5: {note_slug}')

        note_result = subprocess.run(
            [
                VENV_PYTHON, str(publish_note),
                '--slug',        note_slug,
                '--title',       note_title,
                '--date',        date_display,
                '--date-iso',    date_iso,
                '--standfirst',  note_standfirst,
                '--analysis-md', str(note_dir / 'analysis.md'),
                '--token-file',  str(token_file),
                '--scripts-dir', str(anthology_dir),
                '--user-id',     user_id,
            ],
            capture_output=True,
            text=True,
            timeout=240,
        )

        if note_result.returncode != 0:
            logger.error(f'  Note {i+1} publish failed:\n{note_result.stderr}')
            sys.exit(1)

        logger.info(f'  Note {i+1} published: {note_result.stdout.strip()[:150]}')
        note_urls.append(f'/users/{user_id}/notes/{note_slug}.html')

    logger.info('All 5 notes published.')

    # ── Step 6: Build combined-dispatches JSON and write piece dirs ────────────
    logger.info('Step 6: Building combined dispatch JSON…')

    combined_slug = f'd{next_dispatch_num:03d}-daily-edition-{date_iso}'

    combined_entries = []
    for i in range(N_DISPATCHES):
        dispatch_dir = pieces_dispatches_dir / f'd{next_dispatch_num:03d}-{topics[i]["slug"]}-{i+1}'
        dispatch_dir.mkdir(parents=True, exist_ok=True)
        (dispatch_dir / 'analysis.md').write_text(dispatch_bodies[i], encoding='utf-8')
        (dispatch_dir / 'log.md').write_text(
            f"# d{next_dispatch_num:03d} section {i+1} — {topics[i]['title']}\n\n"
            f"**Generated:** {now_utc.isoformat()}Z UTC\n"
            f"**User ID:** {user_id}\n"
            f"**Trigger:** first-dispatch combined edition, section {i+1}/5\n"
            f"**Combined slug:** {combined_slug}\n"
            f"**Note slug:** {topics[i]['note_slug']}\n"
            f"**Word count:** {len(dispatch_bodies[i].split())}\n",
            encoding='utf-8',
        )

        combined_entries.append({
            'label':    ROMAN_LABELS[i],
            'title':    topics[i]['title'],
            'body_md':  dispatch_bodies[i],
            'note_url': note_urls[i],
        })

    # Write combined-dispatches JSON to a temp file
    combined_json_path = Path(tempfile.mkstemp(suffix='.json', prefix='anthology-combined-')[1])
    combined_json_path.write_text(json.dumps(combined_entries, indent=2, ensure_ascii=False),
                                   encoding='utf-8')
    logger.info(f'Combined dispatch JSON written: {combined_json_path}')

    # Edition title: weekday + date, e.g. "Thursday, 14 May 2026"
    edition_title = now_est.strftime('%A, %-d %B %Y')

    # Standfirst for catalog — first dispatch summary
    raw_standfirst = topics[0].get('summary', topics[0]['title'])[:200].strip()
    if raw_standfirst and raw_standfirst[-1] not in '.!?':
        raw_standfirst += '.'
    combined_standfirst = raw_standfirst

    # ── Step 7: Publish combined dispatch ─────────────────────────────────────
    logger.info('Step 7: Publishing combined dispatch…')

    publish_result = subprocess.run(
        [
            VENV_PYTHON, str(publish_disp),
            '--slug',                combined_slug,
            '--title',               edition_title,
            '--date',                date_display,
            '--date-iso',            date_iso,
            '--dispatch-type',       'daily',
            '--standfirst',          combined_standfirst,
            '--combined-dispatches', str(combined_json_path),
            '--token-file',          str(token_file),
            '--scripts-dir',         str(anthology_dir),
            '--user-id',             user_id,
        ],
        capture_output=True,
        text=True,
        timeout=240,
    )

    # Clean up temp file
    combined_json_path.unlink(missing_ok=True)

    if publish_result.returncode != 0:
        logger.error(f'Combined dispatch publish failed:\n{publish_result.stderr}')
        sys.exit(1)

    logger.info(f'Combined dispatch published: {publish_result.stdout.strip()[:200]}')

    # ── Step 8: Regenerate edition.json ───────────────────────────────────────
    logger.info('Step 8: Regenerating edition.json…')

    token     = token_file.read_text(encoding='utf-8').strip()
    clone_dir = Path(f'/tmp/anthology-first-edition-{user_id[:8]}')
    if clone_dir.exists():
        shutil.rmtree(clone_dir)

    try:
        run_cmd(
            f'git clone "https://DonovanBerry11:{token}@github.com/'
            f'DonovanBerry11/anthology.git" {clone_dir}'
        )
        run_cmd([
            VENV_PYTHON,
            str(anthology_dir / 'generate_edition.py'),
            '--user-id',  user_id,
            '--repo-dir', str(clone_dir),
        ])
        run_cmd(f'git -C {clone_dir} config user.email "anthology-server@digitalocean"')
        run_cmd(f'git -C {clone_dir} config user.name "Anthology Server"')
        run_cmd(f'git -C {clone_dir} add users/{user_id}/edition.json')

        commit_result = subprocess.run(
            f'git -C {clone_dir} commit -m '
            f'"Edition: first-dispatch combined for user {user_id[:8]}"',
            shell=True, capture_output=True, text=True,
        )
        if commit_result.returncode == 0:
            run_cmd(f'git -C {clone_dir} push')
            logger.info('edition.json regenerated and pushed')
        else:
            if 'nothing to commit' in commit_result.stdout + commit_result.stderr:
                logger.info('edition.json: no change (already up to date)')
            else:
                logger.warning(f'Edition commit issue: {commit_result.stderr}')

    except RuntimeError as exc:
        logger.warning(f'Edition regeneration failed (non-fatal): {exc}')
        logger.info('Dispatches and notes are live. Edition will update on next cron cycle.')
    finally:
        if clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)

    # ── Done ───────────────────────────────────────────────────────────────────
    total_words = sum(len(b.split()) for b in dispatch_bodies) + sum(len(b.split()) for b in note_bodies)
    logger.info(
        f'✓ First combined dispatch complete: {combined_slug} ({N_DISPATCHES} sections + '
        f'{N_DISPATCHES} notes, {total_words} words total)'
    )
    print(f'✓ First combined dispatch published: {edition_title}')
    print(f'  Combined dispatch: {combined_slug}')
    print(f'  Notes published:   {N_DISPATCHES}')
    print(f'  Note URLs:         {note_urls}')
    print(f'  User:              {user_id}')
    print(f'  Total words:       {total_words}')
    print(f'  Log:               {log_file}')


if __name__ == '__main__':
    main()
