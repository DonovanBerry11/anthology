#!/usr/bin/env python3
"""
run_combined_dispatch.py — Daily autonomous dispatch pipeline.

Replaces the Claude Code agent approach for dispatch generation. Runs daily
(invoked by run_dispatch.sh at 5:07 AM UTC). For each user in the registry:

  1. Select 5 topics from NEWS_TOPIC_QUEUE.md (PENDING entries); fall back to
     web search if the queue has fewer than 5 usable topics.
  2. Generate 5 dispatch bodies (calibrated to the user's orientation).
  3. QC all 5 dispatches in one pass.
  4. Generate 5 companion note bodies (deeper analysis per topic).
  5. Publish each note individually via publish_note.py.
  6. Publish one combined dispatch via publish_dispatch.py --combined-dispatches.
  7. Regenerate edition.json.
  8. Update NEWS_TOPIC_QUEUE.md (mark selected topics COMPLETE).

Usage:
    source /root/anthology-env/bin/activate
    python3 /root/pipeline/run_combined_dispatch.py \
        --env /root/.anthology.env \
        [--dry-run]
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

VENV_PYTHON  = '/root/anthology-env/bin/python3'
MODEL        = 'claude-sonnet-4-20250514'
N_DISPATCHES = 5
ROMAN_LABELS = ['I.', 'II.', 'III.', 'IV.', 'V.']

# How many PENDING topics we need before using the queue exclusively
# (below this threshold we supplement or fall back to web search)
MIN_QUEUE_TOPICS = 5

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_env_file(path: str) -> dict:
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
    parts = []
    for block in response.content:
        if hasattr(block, 'text') and block.text:
            parts.append(block.text)
    return '\n'.join(parts).strip()


def run_cmd(cmd, timeout: int = 240) -> str:
    result = subprocess.run(
        cmd, shell=isinstance(cmd, str),
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Command failed (rc={result.returncode}):\n{result.stderr}")
    return result.stdout.strip()


def safe_slug(text: str, fallback: str = 'dispatch') -> str:
    s = text.lower()
    s = re.sub(r'[^a-z0-9-]', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    return s or fallback


def parse_json_response(text: str, context: str = ''):
    cleaned = re.sub(r'```(?:json)?\s*', '', text)
    cleaned = re.sub(r'```', '', cleaned)
    for pattern in [r'\[.*\]', r'\{.*\}']:
        m = re.search(pattern, cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                continue
    return None


# ── Topics queue utilities ─────────────────────────────────────────────────────

def parse_topics_queue(queue_path: Path) -> list[dict]:
    """
    Parse NEWS_TOPIC_QUEUE.md and return list of PENDING entries.
    Each entry: {title, status, raw_lines, start_idx, end_idx}
    """
    if not queue_path.exists():
        return []

    text  = queue_path.read_text(encoding='utf-8')
    lines = text.splitlines()
    topics = []
    i = 0
    while i < len(lines):
        # Match a topic header: ## Topic Title
        m = re.match(r'^## (.+)', lines[i])
        if m:
            title = m.group(1).strip()
            start_idx = i
            # Collect the block until the next ## or EOF
            j = i + 1
            status = 'UNKNOWN'
            while j < len(lines) and not re.match(r'^## ', lines[j]):
                sm = re.match(r'^\s*Status:\s*(\w+)', lines[j], re.IGNORECASE)
                if sm:
                    status = sm.group(1).upper()
                j += 1
            topics.append({
                'title':     title,
                'status':    status,
                'start_idx': start_idx,
                'end_idx':   j,
            })
            i = j
        else:
            i += 1
    return topics


def mark_topics_complete(queue_path: Path, titles_to_complete: list[str]):
    """Update STATUS: PENDING → STATUS: COMPLETE for the given titles."""
    if not queue_path.exists():
        return
    text = queue_path.read_text(encoding='utf-8')
    for title in titles_to_complete:
        # Replace Status: PENDING within the block following ## <title>
        escaped = re.escape(title)
        text = re.sub(
            rf'(## {escaped}.*?Status:\s*)PENDING',
            r'\1COMPLETE',
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
    queue_path.write_text(text, encoding='utf-8')


# ── Per-user dispatch generation ───────────────────────────────────────────────

def generate_dispatches_for_user(
    user_id: str,
    orientation_path: Path,
    queue_topics: list[dict],
    client: anthropic.Anthropic,
    logger: logging.Logger,
) -> dict:
    """
    Generate 5 dispatch bodies + 5 note bodies for a single user.
    Returns a dict with keys: topics, dispatch_bodies, note_bodies
    """
    orientation_excerpt = orientation_path.read_text(encoding='utf-8')[:2500]

    # ── Topic selection ────────────────────────────────────────────────────────
    pending = [t for t in queue_topics if t['status'] == 'PENDING']

    if len(pending) >= MIN_QUEUE_TOPICS:
        # Use the first N_DISPATCHES PENDING topics from the queue
        selected_queue = pending[:N_DISPATCHES]
        logger.info(f'  Using {N_DISPATCHES} topics from NEWS_TOPIC_QUEUE.md')

        # Ask the model to select/research these queue topics for this user
        queue_titles = '\n'.join(f'- {t["title"]}' for t in selected_queue)
        topic_selection_prompt = f"""You are an editorial agent for Anthology, a personalised newspaper.

READER PROFILE:
{orientation_excerpt}

SELECTED TOPICS FROM NEWS QUEUE (these are the stories to cover today):
{queue_titles}

For each topic, search the web to find the latest developments (past 24–48 hours). \
Then respond with ONLY a valid JSON array of {N_DISPATCHES} objects. No markdown fences:
[
  {{
    "headline": "The actual current headline for this story",
    "summary": "2–3 sentences: what happened and its significance",
    "source": "Publication or outlet name",
    "why_relevant": "One sentence on why this fits this reader's specific interests",
    "suggested_slug": "kebab-case-slug-max-5-words",
    "suggested_title": "Analytical dispatch title (not the headline)",
    "note_slug": "kebab-case-slug-for-companion-note-max-5-words"
  }},
  …
]"""

        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
            messages=[{"role": "user", "content": topic_selection_prompt}],
        )
        topics_text = extract_text(response)
        topics = parse_json_response(topics_text, 'topic selection')
        if not topics or not isinstance(topics, list) or len(topics) < N_DISPATCHES:
            logger.warning('  Topic selection response parse failed — falling back to web search')
            topics = None
        else:
            topics = topics[:N_DISPATCHES]

    else:
        logger.info(f'  Queue has {len(pending)} PENDING topics (< {MIN_QUEUE_TOPICS}) — '
                    'using web search for all topics')
        topics = None

    if topics is None:
        # Web search fallback: find 5 topics directly
        fallback_prompt = f"""You are the editorial agent for Anthology, a personalised newspaper.

READER PROFILE:
{orientation_excerpt}

Search the web for 5 current news stories from the past 48 hours that would genuinely \
interest this reader. Choose stories from different domains so the edition is well-rounded. \
Each story should be substantive and reward analysis.

Respond with ONLY a valid JSON array of {N_DISPATCHES} objects. No markdown fences:
[
  {{
    "headline": "The actual news headline",
    "summary": "2–3 sentences: what happened and its significance",
    "source": "Publication or outlet name",
    "why_relevant": "One sentence on why this fits this reader's interests",
    "suggested_slug": "kebab-case-slug-max-5-words",
    "suggested_title": "Analytical dispatch title (not the headline)",
    "note_slug": "kebab-case-slug-for-companion-note-max-5-words"
  }},
  …
]"""
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}],
            messages=[{"role": "user", "content": fallback_prompt}],
        )
        topics = parse_json_response(extract_text(response), 'fallback topics')
        if not topics or not isinstance(topics, list) or len(topics) < N_DISPATCHES:
            raise RuntimeError('Could not find topics via web search fallback')
        topics = topics[:N_DISPATCHES]

    # Normalise slugs / titles
    for t in topics:
        t['slug']      = safe_slug(t.get('suggested_slug', ''), 'dispatch')
        t['title']     = (t.get('suggested_title') or t.get('headline') or 'Dispatch').strip()
        t['note_slug'] = safe_slug(t.get('note_slug', t['slug'] + '-note'), 'note')

    logger.info(f'  Topics: {[t["title"] for t in topics]}')

    # ── Draft 5 dispatches ─────────────────────────────────────────────────────
    logger.info('  Drafting 5 dispatch bodies…')

    topics_summary = '\n'.join(
        f'{i+1}. TITLE: {t["title"]}\n   Headline: {t["headline"]}\n'
        f'   Summary: {t["summary"]}\n   Source: {t["source"]}'
        for i, t in enumerate(topics)
    )

    dispatch_prompt = f"""You are the writer for Anthology. Write 5 daily dispatches for the \
reader described below.

READER PROFILE:
{orientation_excerpt}

FIVE STORIES TO COVER:
{topics_summary}

Each dispatch must:
- Be 350–450 words
- Use prose paragraphs only — no subheadings, no bullets, no numbered lists
- Open with a strong declarative sentence
- Name the source naturally within the text
- Close with a forward-looking sentence
- NOT include the title, byline, date, or meta-text — body paragraphs only

Respond with ONLY a valid JSON array of {N_DISPATCHES} objects. No markdown fences:
[
  {{"index": 0, "body": "Full dispatch body for story 1…"}},
  …
]"""

    response = client.messages.create(
        model=MODEL, max_tokens=8192,
        messages=[{"role": "user", "content": dispatch_prompt}],
    )
    drafts = parse_json_response(extract_text(response), 'dispatch drafts')
    if not drafts or not isinstance(drafts, list) or len(drafts) < N_DISPATCHES:
        raise RuntimeError('Could not parse dispatch drafts')

    by_idx = {d.get('index', i): d.get('body', '') for i, d in enumerate(drafts)}
    dispatch_bodies = [by_idx.get(i, '').strip() for i in range(N_DISPATCHES)]
    logger.info(f'  Dispatch word counts: {[len(b.split()) for b in dispatch_bodies]}')

    # ── QC ─────────────────────────────────────────────────────────────────────
    logger.info('  Running QC pass…')

    dispatches_for_qc = '\n\n'.join(
        f'=== DISPATCH {i+1} ===\n{body}' for i, body in enumerate(dispatch_bodies)
    )
    qc_prompt = f"""Quality-check these 5 dispatch bodies. For each, verify:
1. Prose only (no subheadings/bullets), 2. 300–500 words, 3. Strong declarative opening,
4. Source named, 5. Forward-looking close.

Respond as JSON array:
[
  {{"index": 0, "result": "PASS"}},
  {{"index": 1, "result": "REVISED", "body": "corrected body…"}},
  …
]

DISPATCHES:
{dispatches_for_qc}"""

    qc_response = client.messages.create(
        model=MODEL, max_tokens=8192,
        messages=[{"role": "user", "content": qc_prompt}],
    )
    qc_data = parse_json_response(extract_text(qc_response), 'QC')
    if qc_data and isinstance(qc_data, list):
        for item in qc_data:
            idx = item.get('index')
            if idx is not None and item.get('result', '').upper().startswith('REVISED'):
                revised = item.get('body', '').strip()
                if revised and len(revised.split()) >= 200:
                    dispatch_bodies[idx] = revised

    # ── Draft 5 companion notes ────────────────────────────────────────────────
    logger.info('  Drafting 5 companion notes…')

    notes_summary = '\n'.join(
        f'{i+1}. TITLE: {topics[i]["title"]}\n'
        f'   Story: {topics[i]["summary"]}\n'
        f'   Dispatch excerpt: {dispatch_bodies[i][:200]}…'
        for i in range(N_DISPATCHES)
    )

    note_prompt = f"""You have written 5 dispatches. Now write 5 companion notes — one per \
story — that go deeper for the reader described below.

READER PROFILE:
{orientation_excerpt}

STORIES:
{notes_summary}

Each note must:
- Be 400–600 words
- Provide structural context, historical background, or analytical depth the dispatch could not
- Use prose paragraphs — no subheadings or bullets
- NOT repeat the dispatch — the reader has already read it
- NOT include title, byline, date, or meta-text

Respond with ONLY a valid JSON array of {N_DISPATCHES} objects. No markdown fences:
[
  {{"index": 0, "body": "Full note body for story 1…"}},
  …
]"""

    response = client.messages.create(
        model=MODEL, max_tokens=8192,
        messages=[{"role": "user", "content": note_prompt}],
    )
    notes_data = parse_json_response(extract_text(response), 'note drafts')
    if not notes_data or not isinstance(notes_data, list) or len(notes_data) < N_DISPATCHES:
        raise RuntimeError('Could not parse note drafts')

    notes_by_idx = {n.get('index', i): n.get('body', '') for i, n in enumerate(notes_data)}
    note_bodies = [notes_by_idx.get(i, '').strip() for i in range(N_DISPATCHES)]
    logger.info(f'  Note word counts: {[len(b.split()) for b in note_bodies]}')

    return {'topics': topics, 'dispatch_bodies': dispatch_bodies, 'note_bodies': note_bodies}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Anthology daily combined dispatch pipeline')
    parser.add_argument('--env',     default='/root/.anthology.env')
    parser.add_argument('--dry-run', action='store_true',
                        help='Generate content but do not publish or push')
    args = parser.parse_args()

    # ── Load credentials ───────────────────────────────────────────────────────
    load_dotenv(args.env)
    file_env = load_env_file(args.env)

    api_key       = file_env.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_API_KEY', '')
    system_dir    = Path(file_env.get('SYSTEM_DIR',    '/root/anthology-system'))
    anthology_dir = Path(file_env.get('ANTHOLOGY_DIR', '/root/anthology'))

    if not api_key:
        print('ERROR: ANTHROPIC_API_KEY not set', file=sys.stderr)
        sys.exit(1)

    # ── Logging ────────────────────────────────────────────────────────────────
    est   = timezone(timedelta(hours=-5))
    today = datetime.now(est).strftime('%Y-%m-%d')
    log_file = system_dir / 'logs' / f'dispatch-{today}.md'
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler(str(log_file)),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger('combined-dispatch')
    logger.info(f'=== Daily combined dispatch run: {today} ===')
    if args.dry_run:
        logger.info('DRY RUN — no publishing or pushing')

    # ── Load registry ──────────────────────────────────────────────────────────
    registry_path = system_dir / 'users' / 'registry.json'
    registry      = json.loads(registry_path.read_text(encoding='utf-8'))
    users         = registry.get('users', [])

    if not users:
        logger.info('No users in registry — nothing to do')
        sys.exit(0)

    logger.info(f'Users to process: {len(users)}')

    # ── Load topics queue ──────────────────────────────────────────────────────
    queue_path   = system_dir / 'NEWS_TOPIC_QUEUE.md'
    queue_topics = parse_topics_queue(queue_path)
    pending_count = sum(1 for t in queue_topics if t['status'] == 'PENDING')
    logger.info(f'NEWS_TOPIC_QUEUE.md: {len(queue_topics)} total, {pending_count} PENDING')

    # ── Piece number bookkeeping ───────────────────────────────────────────────
    pieces_dispatches_dir = system_dir / 'pieces' / 'dispatches'
    pieces_notes_dir      = system_dir / 'pieces' / 'notes'
    pieces_dispatches_dir.mkdir(parents=True, exist_ok=True)
    pieces_notes_dir.mkdir(parents=True, exist_ok=True)

    def next_num(pieces_dir: Path, prefix: str) -> int:
        nums = [
            int(m.group(1))
            for d in pieces_dir.iterdir()
            if d.is_dir()
            for m in [re.match(rf'{re.escape(prefix)}(\d+)', d.name)]
            if m
        ]
        return max(nums, default=0) + 1

    client = anthropic.Anthropic(api_key=api_key)

    # Date strings (shared across all users in this run)
    now_est      = datetime.now(est)
    date_display = now_est.strftime('%B %Y')
    date_iso     = now_est.strftime('%Y-%m-%d')
    edition_title = now_est.strftime('%A, %-d %B %Y')
    now_utc      = datetime.utcnow()

    token_file    = anthology_dir / '.publish-config'
    publish_note  = anthology_dir / 'publish_note.py'
    publish_disp  = anthology_dir / 'publish_dispatch.py'

    completed_topic_titles = []

    # ── Per-user loop ──────────────────────────────────────────────────────────
    for user_entry in users:
        user_id = user_entry['user_id']
        orientation_path = Path(user_entry['orientation_path'])
        logger.info(f'\n── Processing user {user_id[:8]}… ──')

        if not orientation_path.exists():
            logger.warning(f'Orientation not found: {orientation_path} — skipping')
            continue

        try:
            result = generate_dispatches_for_user(
                user_id, orientation_path, queue_topics, client, logger
            )
        except Exception as exc:
            logger.error(f'Generation failed for user {user_id[:8]}: {exc}')
            continue

        topics         = result['topics']
        dispatch_bodies = result['dispatch_bodies']
        note_bodies    = result['note_bodies']

        if args.dry_run:
            logger.info('  DRY RUN: skipping publish steps')
            continue

        next_dispatch_num = next_num(pieces_dispatches_dir, 'd')
        next_note_num     = next_num(pieces_notes_dir, 'n')

        # ── Publish 5 notes ────────────────────────────────────────────────────
        note_urls = []
        for i in range(N_DISPATCHES):
            note_num  = next_note_num + i
            note_slug  = topics[i]['note_slug']
            note_title = f"{topics[i]['title']} — Further Reading"
            raw_sf = topics[i].get('summary', topics[i]['title'])[:200].strip()
            if raw_sf and raw_sf[-1] not in '.!?':
                raw_sf += '.'

            note_dir = pieces_notes_dir / f'n{note_num:03d}-{note_slug}'
            note_dir.mkdir(parents=True, exist_ok=True)
            (note_dir / 'analysis.md').write_text(note_bodies[i], encoding='utf-8')
            (note_dir / 'log.md').write_text(
                f"# n{note_num:03d} — {note_title}\n"
                f"**Generated:** {now_utc.isoformat()}Z\n"
                f"**User:** {user_id}\n**Run:** daily combined dispatch {date_iso}\n",
                encoding='utf-8',
            )

            logger.info(f'  Publishing note {i+1}/5: {note_slug}')
            note_result = subprocess.run(
                [VENV_PYTHON, str(publish_note),
                 '--slug', note_slug, '--title', note_title,
                 '--date', date_display, '--date-iso', date_iso,
                 '--standfirst', raw_sf,
                 '--analysis-md', str(note_dir / 'analysis.md'),
                 '--token-file', str(token_file),
                 '--scripts-dir', str(anthology_dir),
                 '--user-id', user_id],
                capture_output=True, text=True, timeout=240,
            )
            if note_result.returncode != 0:
                logger.error(f'  Note {i+1} failed:\n{note_result.stderr}')
                continue
            logger.info(f'  Note {i+1} ok')
            note_urls.append(f'/users/{user_id}/notes/{note_slug}.html')

        if len(note_urls) < N_DISPATCHES:
            logger.error(f'Only {len(note_urls)}/{N_DISPATCHES} notes published — aborting combined dispatch')
            continue

        # ── Build and publish combined dispatch ────────────────────────────────
        combined_slug = f'd{next_dispatch_num:03d}-daily-edition-{date_iso}'
        combined_entries = []
        for i in range(N_DISPATCHES):
            dispatch_dir = pieces_dispatches_dir / f'd{next_dispatch_num:03d}-{topics[i]["slug"]}-{i+1}'
            dispatch_dir.mkdir(parents=True, exist_ok=True)
            (dispatch_dir / 'analysis.md').write_text(dispatch_bodies[i], encoding='utf-8')
            (dispatch_dir / 'log.md').write_text(
                f"# d{next_dispatch_num:03d} section {i+1} — {topics[i]['title']}\n"
                f"**Generated:** {now_utc.isoformat()}Z\n"
                f"**User:** {user_id}\n**Combined slug:** {combined_slug}\n",
                encoding='utf-8',
            )
            combined_entries.append({
                'label':    ROMAN_LABELS[i],
                'title':    topics[i]['title'],
                'body_md':  dispatch_bodies[i],
                'note_url': note_urls[i],
            })

        combined_json_path = Path(
            tempfile.mkstemp(suffix='.json', prefix='anthology-combined-')[1]
        )
        combined_json_path.write_text(
            json.dumps(combined_entries, indent=2, ensure_ascii=False), encoding='utf-8'
        )

        raw_sf = topics[0].get('summary', topics[0]['title'])[:200].strip()
        if raw_sf and raw_sf[-1] not in '.!?':
            raw_sf += '.'

        logger.info(f'  Publishing combined dispatch: {combined_slug}')
        pub_result = subprocess.run(
            [VENV_PYTHON, str(publish_disp),
             '--slug', combined_slug, '--title', edition_title,
             '--date', date_display, '--date-iso', date_iso,
             '--dispatch-type', 'daily', '--standfirst', raw_sf,
             '--combined-dispatches', str(combined_json_path),
             '--token-file', str(token_file),
             '--scripts-dir', str(anthology_dir),
             '--user-id', user_id],
            capture_output=True, text=True, timeout=240,
        )
        combined_json_path.unlink(missing_ok=True)

        if pub_result.returncode != 0:
            logger.error(f'  Combined dispatch publish failed:\n{pub_result.stderr}')
            continue

        logger.info(f'  Combined dispatch published')

        # ── Regenerate edition.json ────────────────────────────────────────────
        token     = token_file.read_text(encoding='utf-8').strip()
        clone_dir = Path(f'/tmp/anthology-edition-{user_id[:8]}')
        if clone_dir.exists():
            shutil.rmtree(clone_dir)

        try:
            run_cmd(f'git clone "https://DonovanBerry11:{token}@github.com/'
                    f'DonovanBerry11/anthology.git" {clone_dir}')
            run_cmd([VENV_PYTHON, str(anthology_dir / 'generate_edition.py'),
                     '--user-id', user_id, '--repo-dir', str(clone_dir)])
            run_cmd(f'git -C {clone_dir} config user.email "anthology-server@digitalocean"')
            run_cmd(f'git -C {clone_dir} config user.name "Anthology Server"')
            run_cmd(f'git -C {clone_dir} add users/{user_id}/edition.json')
            commit_out = subprocess.run(
                f'git -C {clone_dir} commit -m "Edition: {date_iso} for {user_id[:8]}"',
                shell=True, capture_output=True, text=True,
            )
            if commit_out.returncode == 0:
                run_cmd(f'git -C {clone_dir} push')
                logger.info('  edition.json regenerated and pushed')
            else:
                logger.info('  edition.json: no change')
        except RuntimeError as exc:
            logger.warning(f'  Edition regeneration failed (non-fatal): {exc}')
        finally:
            if clone_dir.exists():
                shutil.rmtree(clone_dir, ignore_errors=True)

        # Track which queue topics were used
        completed_topic_titles.extend(t['title'] for t in topics)
        logger.info(f'  ✓ User {user_id[:8]} complete')

    # ── Update topics queue ────────────────────────────────────────────────────
    if completed_topic_titles and not args.dry_run:
        mark_topics_complete(queue_path, completed_topic_titles)
        logger.info(f'NEWS_TOPIC_QUEUE.md updated: {len(completed_topic_titles)} topics marked COMPLETE')

    logger.info(f'\n=== Daily combined dispatch run complete: {today} ===')
    print(f'✓ Daily combined dispatch run complete. Log: {log_file}')


if __name__ == '__main__':
    main()
