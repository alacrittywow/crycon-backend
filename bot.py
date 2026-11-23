#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Crycon Telegram Bot.

Commands:
    /start
    /help
    /top
    /search nickname
    /profile 44
    /full 44
    /resolve https://x.com/somehandle
"""

import re
import html
import asyncio
from typing import Any, Dict, List

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from crycon.config import load_settings
from crycon.job_payloads import IdentityResolutionPayload, serialize_job_payload
from crycon.supabase_jobs import SupabaseParserJobRepository
from crycon.supabase_repository import SupabaseCandidateRepository
from db_supabase import (
    get_supabase_client,
    clean_text,
    search_candidate_ids,
)

MAX_MESSAGE_LEN = 3900


def parse_allowed_user_ids(value: str) -> frozenset[int]:
    """Parse an optional Telegram allowlist without exposing its contents."""
    items = [item for item in re.split(r"[\s,|]+", value.strip()) if item]
    if not items:
        return frozenset()

    try:
        user_ids = frozenset(int(item) for item in items)
    except ValueError:
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS must contain only numeric user IDs") from None

    if any(user_id <= 0 for user_id in user_ids):
        raise ValueError("TELEGRAM_ALLOWED_USER_IDS must contain only positive user IDs")
    return user_ids


def esc(value: Any) -> str:
    return html.escape(clean_text(value))


def short(value: Any, max_len: int = 600) -> str:
    text = clean_text(value)

    if len(text) <= max_len:
        return text

    return text[:max_len].rstrip() + "..."


def chunk_text(text: str, max_len: int = MAX_MESSAGE_LEN) -> List[str]:
    chunks = []

    while len(text) > max_len:
        cut = text.rfind("\n", 0, max_len)

        if cut == -1:
            cut = max_len

        chunks.append(text[:cut])
        text = text[cut:].lstrip()

    if text:
        chunks.append(text)

    return chunks


async def reply_long(update: Update, text: str) -> None:
    for chunk in chunk_text(text):
        await update.message.reply_text(
            chunk,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


def fetch_candidate(client, candidate_id: int) -> Dict[str, Any]:
    return SupabaseCandidateRepository(client).get_candidate(candidate_id) or {}


def fetch_profiles(client, candidate_id: int) -> List[Dict[str, Any]]:
    return SupabaseCandidateRepository(client).list_profiles(candidate_id)


def fetch_contacts(client, candidate_id: int) -> List[Dict[str, Any]]:
    return SupabaseCandidateRepository(client).list_contacts(candidate_id)


def fetch_wallets(client, candidate_id: int) -> List[Dict[str, Any]]:
    return SupabaseCandidateRepository(client).list_wallets(candidate_id)


def fetch_evidence(client, candidate_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    return SupabaseCandidateRepository(client).list_evidence(candidate_id, limit)


def get_top_candidate_ids(client, limit: int = 10) -> List[int]:
    return SupabaseCandidateRepository(client).list_top_candidate_ids(limit)


def format_short_profile(client, candidate_id: int) -> str:
    candidate = fetch_candidate(client, candidate_id)

    if not candidate:
        return f"Candidate not found: {candidate_id}"

    profiles = fetch_profiles(client, candidate_id)

    lines = []

    lines.append(f"<b>Candidate ID:</b> {esc(candidate.get('id'))}")
    lines.append(f"<b>Username:</b> {esc(candidate.get('main_username'))}")
    lines.append(f"<b>Display name:</b> {esc(candidate.get('display_name'))}")
    lines.append(f"<b>Status:</b> {esc(candidate.get('status'))}")
    lines.append("")
    lines.append(f"<b>Overall trust:</b> {esc(candidate.get('overall_trust_score'))}/100")
    lines.append(f"<b>Relevance:</b> {esc(candidate.get('relevance_score'))}/100")
    lines.append(f"<b>Identity:</b> {esc(candidate.get('identity_score'))}/100")
    lines.append(f"<b>Wallet score:</b> {esc(candidate.get('wallet_score'))}/100")
    lines.append(f"<b>Contact score:</b> {esc(candidate.get('contact_score'))}/100")

    bio = clean_text(candidate.get("bio"))

    if bio:
        lines.append("")
        lines.append("<b>Bio:</b>")
        lines.append(esc(short(bio, 700)))

    lines.append("")
    lines.append("<b>Profiles:</b>")

    if profiles:
        for profile in profiles[:5]:
            platform = esc(profile.get("platform"))
            username = esc(profile.get("username"))
            profile_url = esc(profile.get("profile_url"))
            source_url = esc(profile.get("source_url"))
            confidence = esc(profile.get("confidence"))

            lines.append(f"• <b>{platform}</b>: {username}")
            if profile_url:
                lines.append(f"  profile: {profile_url}")
            if source_url:
                lines.append(f"  source: {source_url}")
            lines.append(f"  confidence: {confidence}")
    else:
        lines.append("• none")

    lines.append("")
    lines.append(f"Full evidence: <code>/full {candidate_id}</code>")

    return "\n".join(lines)


def format_full_profile(client, candidate_id: int) -> str:
    candidate = fetch_candidate(client, candidate_id)

    if not candidate:
        return f"Candidate not found: {candidate_id}"

    profiles = fetch_profiles(client, candidate_id)
    contacts = fetch_contacts(client, candidate_id)
    wallets = fetch_wallets(client, candidate_id)
    evidence = fetch_evidence(client, candidate_id, limit=12)

    text = format_short_profile(client, candidate_id)

    lines = [text, ""]

    lines.append("<b>Contacts:</b>")

    useful_contacts = sorted(
        contacts,
        key=lambda item: int(item.get("confidence") or 0),
        reverse=True,
    )

    if useful_contacts:
        for contact in useful_contacts[:10]:
            lines.append(
                f"• {esc(contact.get('contact_type'))}: "
                f"{esc(contact.get('value'))} "
                f"| confidence={esc(contact.get('confidence'))}"
            )
            if contact.get("evidence_url"):
                lines.append(f"  evidence: {esc(contact.get('evidence_url'))}")

        if len(useful_contacts) > 10:
            lines.append(f"• hidden {len(useful_contacts) - 10} more contacts")
    else:
        lines.append("• none")

    lines.append("")
    lines.append("<b>Wallets:</b>")

    if wallets:
        for wallet in wallets[:10]:
            value = wallet.get("wallet_address") or wallet.get("name_service")
            lines.append(
                f"• {esc(wallet.get('wallet_type'))}: "
                f"{esc(value)} "
                f"| chain={esc(wallet.get('chain'))} "
                f"| confidence={esc(wallet.get('confidence'))}"
            )
            if wallet.get("evidence_url"):
                lines.append(f"  evidence: {esc(wallet.get('evidence_url'))}")
            if wallet.get("evidence_text"):
                lines.append(f"  text: {esc(short(wallet.get('evidence_text'), 250))}")

        if len(wallets) > 10:
            lines.append(f"• hidden {len(wallets) - 10} more wallets")
    else:
        lines.append("• none")

    lines.append("")
    lines.append("<b>Evidence:</b>")

    if evidence:
        for item in evidence[:10]:
            lines.append(
                f"• {esc(item.get('entity_type'))}: "
                f"{esc(item.get('entity_value'))} "
                f"| confidence={esc(item.get('confidence'))}"
            )
            if item.get("source_url"):
                lines.append(f"  source: {esc(item.get('source_url'))}")
            if item.get("evidence_text"):
                lines.append(f"  text: {esc(short(item.get('evidence_text'), 250))}")
    else:
        lines.append("• none")

    return "\n".join(lines)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = """
<b>Crycon Web3 Research Bot</b>

Commands:

<code>/top</code>
Show top candidates.

<code>/search nickname</code>
Search by username, contact, wallet, ENS or .sol.

<code>/profile 44</code>
Show short candidate card.

<code>/full 44</code>
Show contacts, wallets and evidence.

<code>/resolve https://x.com/somehandle</code>
Resolve X/ENS/Farcaster/Lens/wallet via public identity signals.
""".strip()

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_command(update, context)


async def access_denied_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    if update.message:
        await update.message.reply_text("Access denied.")


async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = get_supabase_client()

    candidate_ids = await asyncio.to_thread(
        get_top_candidate_ids,
        client,
        10,
    )

    if not candidate_ids:
        await update.message.reply_text("No candidates found.")
        return

    lines = ["<b>Top candidates</b>", ""]

    for candidate_id in candidate_ids:
        candidate = fetch_candidate(client, candidate_id)

        if not candidate:
            continue

        lines.append(
            f"#{esc(candidate.get('id'))} "
            f"{esc(candidate.get('main_username'))} "
            f"| trust={esc(candidate.get('overall_trust_score'))} "
            f"| status={esc(candidate.get('status'))}"
        )
        lines.append(f"Open: <code>/profile {candidate_id}</code>")
        lines.append("")

    await reply_long(update, "\n".join(lines))


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip()

    if not query:
        await update.message.reply_text("Usage: /search nickname")
        return

    client = get_supabase_client()

    candidate_ids = await asyncio.to_thread(
        search_candidate_ids, client, query, 10
    )

    if not candidate_ids:
        await update.message.reply_text(f"No matches for: {query}")
        return

    lines = [f"<b>Search:</b> {esc(query)}", f"<b>Matches:</b> {len(candidate_ids)}", ""]

    for candidate_id in candidate_ids:
        candidate = fetch_candidate(client, candidate_id)

        if not candidate:
            continue

        lines.append(
            f"#{esc(candidate.get('id'))} "
            f"{esc(candidate.get('main_username'))} "
            f"| trust={esc(candidate.get('overall_trust_score'))} "
            f"| status={esc(candidate.get('status'))}"
        )
        lines.append(f"Open: <code>/profile {candidate_id}</code>")
        lines.append("")

    await reply_long(update, "\n".join(lines))


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /profile 44")
        return

    try:
        candidate_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Candidate ID must be a number.")
        return

    client = get_supabase_client()

    text = await asyncio.to_thread(
        format_short_profile,
        client,
        candidate_id,
    )

    await reply_long(update, text)


async def full_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /full 44")
        return

    try:
        candidate_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Candidate ID must be a number.")
        return

    client = get_supabase_client()

    text = await asyncio.to_thread(
        format_full_profile,
        client,
        candidate_id,
    )

    await reply_long(update, text)


def enqueue_identity_job(client, identity: str, idempotency_key: str) -> Dict[str, Any]:
    payload = IdentityResolutionPayload(
        job_type="identity_resolution",
        identity=identity,
    )
    return SupabaseParserJobRepository(client).enqueue_job(
        job_type=payload.job_type,
        query=serialize_job_payload(payload),
        idempotency_key=idempotency_key,
        max_attempts=payload.max_attempts,
    )


async def resolve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    identity = " ".join(context.args).strip()

    if not identity:
        await update.message.reply_text("Usage: /resolve https://x.com/somehandle")
        return

    client = get_supabase_client()
    job = await asyncio.to_thread(
        enqueue_identity_job,
        client,
        identity,
        f"telegram:resolve:{update.update_id}",
    )
    await update.message.reply_text(
        f"Resolve job queued: #{job['id']}\n"
        f"Status: {job['status']}\n"
        f"Check: /job {job['id']}"
    )

async def resolve_full_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    identity = " ".join(context.args).strip()

    if not identity:
        await update.message.reply_text("Usage: /resolve_full https://x.com/somehandle")
        return

    client = get_supabase_client()
    job = await asyncio.to_thread(
        enqueue_identity_job,
        client,
        identity,
        f"telegram:resolve-full:{update.update_id}",
    )
    await update.message.reply_text(
        f"Full resolve job queued: #{job['id']}\n"
        f"Status: {job['status']}\n"
        f"Check: /job {job['id']}"
    )


async def job_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: /job 123")
        return
    try:
        job_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Job ID must be a number.")
        return

    repository = SupabaseParserJobRepository(get_supabase_client())
    job = await asyncio.to_thread(repository.get_job, job_id)
    if not job:
        await update.message.reply_text(f"Job not found: {job_id}")
        return
    text = (
        f"<b>Job #{esc(job.get('id'))}</b>\n"
        f"Type: {esc(job.get('job_type'))}\n"
        f"Status: {esc(job.get('status'))}\n"
        f"Attempt: {esc(job.get('attempt_count'))}/{esc(job.get('max_attempts'))}\n"
        f"Result count: {esc(job.get('result_count'))}\n"
        f"Error: {esc(job.get('error_text') or 'none')}"
    )
    await reply_long(update, text)


def build_application():
    settings = load_settings()
    token = settings.require("TELEGRAM_BOT_TOKEN")
    allowed_user_ids = parse_allowed_user_ids(settings.text("TELEGRAM_ALLOWED_USER_IDS"))

    app = Application.builder().token(token).build()
    allowed_users = (
        filters.User(user_id=list(allowed_user_ids))
        if allowed_user_ids
        else None
    )

    app.add_handler(CommandHandler("start", start_command, filters=allowed_users))
    app.add_handler(CommandHandler("help", help_command, filters=allowed_users))
    app.add_handler(CommandHandler("top", top_command, filters=allowed_users))
    app.add_handler(CommandHandler("search", search_command, filters=allowed_users))
    app.add_handler(CommandHandler("profile", profile_command, filters=allowed_users))
    app.add_handler(CommandHandler("full", full_command, filters=allowed_users))
    app.add_handler(CommandHandler("resolve", resolve_command, filters=allowed_users))
    app.add_handler(CommandHandler("resolve_full", resolve_full_command, filters=allowed_users))
    app.add_handler(CommandHandler("job", job_command, filters=allowed_users))
    if allowed_users:
        app.add_handler(MessageHandler(filters.COMMAND & ~allowed_users, access_denied_command))

    return app


def main() -> None:
    app = build_application()

    print("=" * 90)
    print("Crycon Telegram Bot is running")
    print("=" * 90)

    app.run_polling()


if __name__ == "__main__":
    main()
