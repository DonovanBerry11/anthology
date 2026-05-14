#!/usr/bin/env python3
"""
first_dispatch.py — Generates and publishes a single personalised dispatch
for a new user immediately after bootstrap completes.

Runs on the server only (/root/pipeline/). Called by bootstrap_server.py via
subprocess.Popen (non-blocking) after /first-dispatch is hit.

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
from datetime import datetime, timezone, timedelta
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# ── Constants ─────────────────────────────────────────────────────────────────

VENV_PYTHON = '/root/anthology-env/bin/python3'
MODEL       = 'claude-sonnet-4-20250514'

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


def run_cmd(cmd, timeout: int = 120) -> str:
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Generate and publish a first personalised dispatch for a new user'
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
    logger.info(f'Starting first dispatch for user_id={user_id}')

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

    # First ~2500 chars covers Stated Preferences and profile — enough context
    orientation_excerpt = orientation_path.read_text(encoding='utf-8')[:2500]
    logger.info(f'Loaded orientation: {orientation_path}')

    # ── Next dispatch number ───────────────────────────────────────────────────
    pieces_dispatches_dir = system_dir / 'pieces' / 'dispatches'
    pieces_dispatches_dir.mkdir(parents=True, exist_ok=True)

    existing_nums = [
        int(m.group(1))
        for d in pieces_dispatches_dir.iterdir()
        if d.is_dir()
        for m in [re.match(r'd(\d+)', d.name)]
        if m
    ]
    next_num = max(existing_nums, default=0) + 1
    logger.info(f'Next dispatch number: {next_num}')

    # ── Anthropic client ────────────────────────────────────────────────────────
    client = anthropic.Anthropic(api_key=api_key)

    # ── Step 1: Find topic via web search ──────────────────────────────────────
    logger.info('Step 1: Finding topic with web search...')

    topic_prompt = f"""You are the editorial agent for Anthology, a personalised newspaper. \
A new reader has just completed onboarding and their first edition is empty. \
You need to find a current news story to anchor their first dispatch.

READER PROFILE (from their orientation file):
{orientation_excerpt}

Search the web for a current news story from the past 24–48 hours that would \
genuinely interest this reader based on their stated background and interests. \
Choose something substantive — a political, economic, geopolitical, financial, \
or technology development that rewards analysis. Avoid soft news.

After searching, respond with ONLY a valid JSON object in this exact format \
(no markdown fences, no commentary, just the JSON):
{{
  "headline": "The actual news headline",
  "summary": "2–3 sentences summarising what happened and its immediate significance",
  "source": "Publication or news outlet name",
  "why_relevant": "One sentence on why this story fits this reader's specific interests",
  "suggested_slug": "kebab-case-slug-max-5-words",
  "suggested_title": "An analytical dispatch title (not the news headline — something that frames the story analytically)"
}}"""

    topic_response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
        }],
        messages=[{"role": "user", "content": topic_prompt}],
    )

    topic_text = extract_text(topic_response)
    logger.info(f'Topic response (first 300 chars): {topic_text[:300]}')

    # Extract JSON — be tolerant of markdown fences the model might add
    json_match = re.search(r'\{[^{}]*"headline"[^{}]*\}', topic_text, re.DOTALL)
    if not json_match:
        # Fallback: try the whole response as JSON
        json_match = re.search(r'\{.*\}', topic_text, re.DOTALL)
    if not json_match:
        logger.error(f'Could not parse topic JSON. Full response:\n{topic_text}')
        sys.exit(1)

    try:
        topic = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        logger.error(f'JSON parse error: {exc}\nMatched text: {json_match.group()}')
        sys.exit(1)

    raw_slug = topic.get('suggested_slug', 'first-dispatch').lower()
    slug = re.sub(r'[^a-z0-9-]', '-', raw_slug)
    slug = re.sub(r'-+', '-', slug).strip('-') or 'first-dispatch'
    title = (topic.get('suggested_title') or topic.get('headline') or 'First Dispatch').strip()

    logger.info(f'Topic selected: {title} (slug: {slug})')

    # ── Step 2: Draft the dispatch ──────────────────────────────────────────────
    logger.info('Step 2: Drafting dispatch...')

    draft_prompt = f"""You are the writer for Anthology, a personalised analytical newspaper. \
Write a daily dispatch for the reader described below.

READER PROFILE:
{orientation_excerpt}

NEWS STORY:
Headline: {topic.get('headline', '')}
Summary: {topic.get('summary', '')}
Source: {topic.get('source', '')}
Why relevant to this reader: {topic.get('why_relevant', '')}

DISPATCH TITLE: {title}

FORMAT REQUIREMENTS:
- Length: 350–450 words
- Structure: prose paragraphs only — no subheadings, no bullet points, no numbered lists, \
no headers, no bold labels
- Voice: analytical, precise, direct — serious newspaper tone calibrated to this reader's sophistication
- Coverage: what happened, its immediate significance, and the broader structural context
- Attribution: name the source ({topic.get('source', 'source')}) naturally within the text
- Personalisation: write specifically for this reader's background, not a generic audience
- Opening: a strong declarative sentence — not a question, not "In recent weeks", \
not "It was announced that"
- Closing: a forward-looking sentence about what to watch or what this sets in motion
- Do not include the dispatch title, byline, date, or any meta-text — body paragraphs only

Write the dispatch body now:"""

    draft_response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": draft_prompt}],
    )

    draft_text = extract_text(draft_response).strip()
    word_count = len(draft_text.split())
    logger.info(f'Draft complete: {word_count} words')

    # ── Step 3: Lightweight QC ─────────────────────────────────────────────────
    logger.info('Step 3: Quality check...')

    qc_prompt = f"""You are a quality editor for Anthology, a personalised newspaper. \
Review the dispatch below against these criteria:

1. STRUCTURE: Prose paragraphs only — no subheadings, bullets, bold labels, or lists?
2. GROUNDED: Factually consistent with the news story provided?
3. ATTRIBUTED: Source ({topic.get('source', 'source')}) named naturally in the text?
4. LENGTH: Between 300 and 500 words? (Current count: ~{word_count})
5. OPENING/CLOSING: Strong declarative opening; forward-looking close?

If all five pass without issue, respond with exactly:
PASS

If there are fixable issues, respond with:
REVISED
[the corrected full dispatch body — same format requirements, no meta-text]

DISPATCH TITLE: {title}

DISPATCH TEXT:
{draft_text}

NEWS CONTEXT:
{topic.get('headline', '')} — {topic.get('summary', '')} (Source: {topic.get('source', '')})"""

    qc_response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": qc_prompt}],
    )

    qc_text = extract_text(qc_response).strip()

    if qc_text.upper().startswith('REVISED'):
        revised_body = qc_text[len('REVISED'):].strip()
        if revised_body and len(revised_body.split()) >= 200:
            draft_text = revised_body
            logger.info(f'QC: dispatch revised ({len(draft_text.split())} words after revision)')
        else:
            logger.warning('QC: REVISED response too short or empty — keeping original draft')
    else:
        logger.info(f'QC result: {qc_text[:80]}')

    # ── Build standfirst ───────────────────────────────────────────────────────
    raw_standfirst = (topic.get('summary') or topic.get('headline') or title).strip()
    if len(raw_standfirst) > 200:
        trimmed = raw_standfirst[:200]
        last_period = trimmed.rfind('.')
        raw_standfirst = (
            trimmed[:last_period + 1] if last_period > 80 else trimmed.rstrip() + '.'
        )
    standfirst = raw_standfirst.strip()
    if standfirst and standfirst[-1] not in '.!?':
        standfirst += '.'

    # ── Write piece directory ──────────────────────────────────────────────────
    piece_dir  = pieces_dispatches_dir / f'd{next_num:03d}-{slug}'
    piece_dir.mkdir(parents=True, exist_ok=True)

    analysis_md = piece_dir / 'analysis.md'
    analysis_md.write_text(draft_text, encoding='utf-8')

    now_utc = datetime.utcnow()
    log_md_content = f"""# d{next_num:03d} — {title}

**Generated:** {now_utc.isoformat()}Z UTC
**User ID:** {user_id}
**Trigger:** first-dispatch (post-onboarding bootstrap)
**Model:** {MODEL}
**Topic source:** web search (web_search_20250305)
**News headline:** {topic.get('headline', '—')}
**News source:** {topic.get('source', '—')}
**Slug:** {slug}
**Word count:** {len(draft_text.split())}
**QC result:** {qc_text[:120]}
**Standfirst:** {standfirst}
"""
    (piece_dir / 'log.md').write_text(log_md_content, encoding='utf-8')
    logger.info(f'Piece directory written: {piece_dir}')

    # ── Date strings ───────────────────────────────────────────────────────────
    now_est      = datetime.now(est)
    date_display = now_est.strftime('%B %Y')   # e.g. "May 2026"
    date_iso     = now_est.strftime('%Y-%m-%d')

    # ── Step 4: Publish dispatch ───────────────────────────────────────────────
    logger.info('Step 4: Publishing dispatch...')

    token_file     = anthology_dir / '.publish-config'
    publish_script = anthology_dir / 'publish_dispatch.py'

    publish_result = subprocess.run(
        [
            VENV_PYTHON, str(publish_script),
            '--slug',          slug,
            '--title',         title,
            '--date',          date_display,
            '--date-iso',      date_iso,
            '--dispatch-type', 'daily',
            '--standfirst',    standfirst,
            '--analysis-md',   str(analysis_md),
            '--token-file',    str(token_file),
            '--scripts-dir',   str(anthology_dir),
            '--user-id',       user_id,
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    if publish_result.returncode != 0:
        logger.error(f'Publish failed:\n{publish_result.stderr}')
        sys.exit(1)

    logger.info(f'Publish stdout:\n{publish_result.stdout.strip()}')

    # ── Step 5: Regenerate edition.json ───────────────────────────────────────
    logger.info('Step 5: Regenerating edition.json...')

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

        # Commit (may produce "nothing to commit" — that's fine)
        commit_result = subprocess.run(
            f'git -C {clone_dir} commit -m "Edition: first-dispatch for user {user_id[:8]}"',
            shell=True, capture_output=True, text=True,
        )
        if commit_result.returncode == 0:
            run_cmd(f'git -C {clone_dir} push')
            logger.info('Edition.json regenerated and pushed')
        else:
            if 'nothing to commit' in commit_result.stdout + commit_result.stderr:
                logger.info('Edition.json: no change (already up to date)')
            else:
                logger.warning(f'Edition commit issue: {commit_result.stderr}')

    except RuntimeError as exc:
        # Non-fatal — dispatch is live; edition regenerates on next cron run
        logger.warning(f'Edition regeneration failed (non-fatal): {exc}')
        logger.info('Dispatch is published. Edition will update on next cron cycle.')
    finally:
        if clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)

    # ── Done ───────────────────────────────────────────────────────────────────
    logger.info(
        f'✓ First dispatch complete: d{next_num:03d}-{slug} — {title}'
    )
    print(f'✓ First dispatch published: {title}')
    print(f'  Piece:  d{next_num:03d}-{slug}')
    print(f'  User:   {user_id}')
    print(f'  Words:  {len(draft_text.split())}')
    print(f'  Log:    {log_file}')


if __name__ == '__main__':
    main()
