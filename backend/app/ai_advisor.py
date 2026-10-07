"""LLM-written reasoning on top of the numbers this app already computes.

Every other recommendation in this app is arithmetic: a projection, a rank,
a percentage. That is the right way round -- the maths is auditable and it
runs for free. What it can't do is weigh three considerations against each
other in a sentence ("take the lower projection, because the floor matters
when you're favoured by 20"). That is what this module is for.

Two rules shape everything here:

1. **The model explains, it does not compute.** The prompt carries the
   figures the app derived from ESPN, nflverse and FantasyCalc, and the
   system prompt forbids inventing any others. An LLM asked for "this
   week's projections" will happily produce confident numbers that are
   nothing of the kind, and a fantasy tool that mixes real and imagined
   stats is worse than one with no commentary at all.

2. **The credential is the user's own.** There is no instance-wide API
   key, deliberately: these calls are billed to whoever's key makes them,
   and an operator-level key would mean one person paying for everyone
   else's analysis. Premium accounts save their own key in Settings ->
   Account; see models.User.ai_api_key.

Failures surface as AiAdvisorError with a message meant for a person, not a
stack trace -- a wrong key, an exhausted quota and a provider outage all
need different actions from the user, and "500 Internal Server Error" tells
them none of it.
"""

from __future__ import annotations

import datetime
import time

from sqlalchemy.orm import Session

from app import chatgpt_oauth
from app.models import User

# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

ANTHROPIC = "anthropic"
OPENAI = "openai"
PROVIDERS = (ANTHROPIC, OPENAI)

PROVIDER_LABELS = {ANTHROPIC: "Claude (Anthropic)", OPENAI: "OpenAI"}

# Defaults chosen for this job: a few hundred words of reasoning over a small
# factual payload. Both are overridable per account (User.ai_model) because a
# key without access to the default would otherwise be stuck -- the provider's
# own "model not found" is the clearest possible signal, but only if there's a
# way to act on it.
DEFAULT_MODELS = {
    ANTHROPIC: "claude-opus-5-5",
    OPENAI: "gpt-6.1-sol",
}

# Generous enough that thinking/reasoning tokens plus ~600 words of prose fit
# comfortably. Both families spend part of this budget reasoning before they
# write anything, so a tight cap doesn't produce a shorter answer -- it
# produces an empty one, truncated mid-thought.
MAX_OUTPUT_TOKENS = 8000

# Longer than any other outbound call in this app (see espn_client's 20s),
# because a reasoning model legitimately takes a while to think. Has to stay
# below nginx's proxy_read_timeout (300s in deploy/nginx.conf.template) or
# the browser gets a 504 while the request is still in flight and being
# billed.
REQUEST_TIMEOUT_SECONDS = 120.0

# Bounds the prompt regardless of league size, so a 14-team league with a
# full waiver wire can't quietly cost ten times what a 10-team one does.
MAX_PROMPT_CHARS = 12000


class AiAdvisorError(Exception):
    """Something the user can fix: no key saved, a key the provider
    rejected, a model their account can't use, nothing to analyse yet.
    Carries a message intended for a person, not a log line."""


class AiRateLimitError(AiAdvisorError):
    """Too many analyses from this account in the last hour."""


class AiProviderError(AiAdvisorError):
    """The provider was reachable-ish but didn't produce an answer: a
    timeout, a network failure, a 5xx, or a response with no prose in it.
    Separate from the base class because there is nothing for the user to
    change — the only sensible advice is to try again."""


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

# In-process and dependency-free, same approach and same caveats as the login
# throttle in app/auth.py: the deployed service runs two workers, so the real
# ceiling is roughly double this. The point isn't precision, it's that a stuck
# retry loop in a browser tab can't run up somebody's bill overnight.
MAX_CALLS_PER_HOUR = 20
RATE_WINDOW_SECONDS = 60 * 60
_calls: dict[int, list[float]] = {}


def _recent_calls(user_id: int, now: float) -> list[float]:
    recent = [at for at in _calls.get(user_id, []) if now - at < RATE_WINDOW_SECONDS]
    if recent:
        _calls[user_id] = recent
    else:
        _calls.pop(user_id, None)
    return recent


def check_rate_limit(user_id: int) -> None:
    """Raise once this account has asked for too many analyses this hour."""
    now = time.monotonic()
    for other in list(_calls):
        _recent_calls(other, now)
    recent = _recent_calls(user_id, now)
    if len(recent) >= MAX_CALLS_PER_HOUR:
        minutes = int((RATE_WINDOW_SECONDS - (now - min(recent))) / 60) + 1
        raise AiRateLimitError(
            f"That's {MAX_CALLS_PER_HOUR} analyses in the last hour — the limit is there so a "
            f"runaway page can't run up your API bill. Try again in about {minutes} minutes."
        )


def record_call(user_id: int) -> None:
    _calls.setdefault(user_id, []).append(time.monotonic())


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


# How an account pays for its calls. "api_key" bills the provider account the
# key belongs to; "chatgpt_plan" spends a ChatGPT Plus/Pro allowance via
# Sign in with ChatGPT (OpenAI only — Anthropic prohibits the equivalent for
# third-party apps, see app/chatgpt_oauth.py's module docstring).
API_KEY = "api_key"
CHATGPT_PLAN = "chatgpt_plan"


def auth_mode(user: User) -> str | None:
    """Which credential this account is actually using, or None."""
    provider = normalize_provider(user.ai_provider)
    if provider is None:
        return None
    if provider == OPENAI and (user.ai_oauth or {}).get("access_token"):
        return CHATGPT_PLAN
    return API_KEY if user.ai_api_key else None


def normalize_provider(value: str | None) -> str | None:
    """Returns a known provider id, or None for anything else — including
    the empty string, which is how the UI says "disconnect"."""
    candidate = (value or "").strip().lower()
    return candidate if candidate in PROVIDERS else None


def resolved_model(user: User) -> str | None:
    provider = normalize_provider(user.ai_provider)
    if provider is None:
        return None
    return (user.ai_model or "").strip() or DEFAULT_MODELS[provider]


def is_configured(user: User) -> bool:
    return auth_mode(user) is not None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a fantasy football analyst embedded in a tool that \
has already done the arithmetic. You are given that tool's own computed figures, \
derived from the user's real ESPN league, nflverse play-by-play data and \
FantasyCalc market values.

Your job is to reason over those figures and say what you'd actually do.

Hard rules:
- Use ONLY the numbers in the data below. Never state a projection, rank, \
yardage figure, snap share or market value that isn't there. If something you'd \
want isn't provided, say what's missing rather than guessing at it.
- You have no knowledge of this season's results, injuries or news beyond what \
is in the data. Don't imply otherwise.
- Disagree with the tool's ranking when the figures support it, and say why. \
Agreeing with every row is not useful.
- Name the tradeoff, not just the winner: floor vs ceiling, this week vs rest of \
season, what has to be true for the call to be wrong.

Style: plain prose for a league manager in a hurry. Lead with the decision. \
Markdown headings and short bullet lists are fine; tables are not. Under 400 \
words. No preamble, no sign-off, no restating these instructions."""


def _fmt(value, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _matchup_line(matchup: dict | None) -> str:
    """The evidence behind a 'tough'/'favorable' rating, compactly.

    Deliberately the real defensive figure rather than the rating alone —
    "tough matchup" is an assertion, "allows 71 rush yds/g, league average
    112" is the thing it was derived from. Mirrors the UI's matchupDetail().
    """
    if not matchup:
        return "no matchup data"
    parts = [f"vs {matchup.get('opponent') or '?'}"]
    rank, total = matchup.get("defense_rank"), matchup.get("defense_teams_ranked")
    position = matchup.get("position") or "this position"
    if rank and total:
        parts.append(f"ranked {rank} of {total} vs {position}")
    value, metric = matchup.get("value"), matchup.get("metric")
    if value is not None:
        detail = f"allows {_fmt(value)} {metric or 'units'}/g"
        average = matchup.get("league_average")
        if average is not None:
            detail += f" (league avg {_fmt(average)})"
        parts.append(detail)
    if matchup.get("source") == "dst_projection":
        # The weakest of the three sources: the opponent's own projected D/ST
        # score standing in for defensive strength. Flagged so the model
        # doesn't present a proxy as a measurement.
        parts.append("NOTE: proxy figure, not real yardage allowed")
    label = matchup.get("label")
    if label:
        parts.append(f"rated {label}")
    return "; ".join(parts)


def _trend_line(trend: dict | None) -> str:
    """Recent usage, as the weekly values themselves.

    The per-week numbers go in rather than only the up/down/flat rating, so
    the model can tell a genuine climb from one spike in a four-week sample
    — that distinction is most of the value of looking at usage at all.
    `stats` is ordered by position priority (see trends.POSITION_TREND_STATS),
    so the first entries are the ones that matter for this position.
    """
    stats = (trend or {}).get("stats") or {}
    if not stats:
        return "no usage trend"
    weeks = trend.get("weeks_counted")
    parts = []
    for entry in list(stats.values())[:3]:
        values = entry.get("recent") or []
        rendered = ", ".join(_fmt(v) for v in values)
        parts.append(f"{entry.get('label')} {entry.get('trend') or 'flat'} ({rendered})")
    prefix = f"last {weeks} played wks" if weeks else "recent"
    return f"{prefix}: " + "; ".join(parts)


def _player_line(player: dict, position: str | None = None) -> str:
    """One player as a single line of facts.

    `position` is a fallback for callers whose payload doesn't carry it —
    the waiver lists group by position rather than repeating it per row
    (see waivers.add_payload), and "(?)" in a prompt invites the model to
    guess at it.
    """
    bits = [
        f"{player.get('name')} ({player.get('position') or position or '?'})",
        f"proj {_fmt(player.get('projected_points'))}",
    ]
    if player.get("injury_status") and player["injury_status"].upper() not in ("ACTIVE", "NORMAL"):
        bits.append(f"injury {player['injury_status']}")
    if player.get("percent_owned") is not None:
        bits.append(f"{_fmt(player['percent_owned'])}% owned")
    bits.append(_matchup_line(player.get("matchup")))
    if "trend" in player:
        bits.append(_trend_line(player.get("trend")))
    return " | ".join(bits)


def build_start_sit_prompt(data: dict) -> str:
    lines = [
        f"LEAGUE: week {data.get('week') or '?'} — my team is {data.get('team') or 'unknown'}.",
        "",
        "The tool compared my current lineup against the highest-projected eligible "
        "player for each slot. Its suggestions are below; judge them.",
        "",
    ]
    for row in (data.get("lineup") or [])[:24]:
        marker = "SWAP SUGGESTED" if row.get("swap_recommended") else "no change suggested"
        lines.append(f"[{row.get('slot')}] {marker}")
        lines.append(f"  starting now: {_player_line(row.get('current_starter') or {})}")
        if row.get("swap_recommended"):
            lines.append(f"  tool prefers:  {_player_line(row.get('recommended_starter') or {})}")
            if row.get("reason"):
                lines.append(f"  tool's reason: {row['reason']}")
        lines.append("")
    lines.append(
        "Tell me which of these swaps to actually make and which to ignore. Where the "
        "projections are close, say what breaks the tie — the defensive figures above, "
        "injury status, or a bye. Flag any slot where the tool is leaning on a thin number."
    )
    return "\n".join(lines)


def build_waivers_prompt(data: dict) -> str:
    lines = [f"LEAGUE: my team is {data.get('team') or 'unknown'}."]

    budget = data.get("budget") or {}
    if budget.get("type") == "faab":
        lines.append(
            f"WAIVERS: FAAB. I have ${budget.get('my_remaining')} of ${budget.get('budget')} left. "
            f"The richest rival still has ${budget.get('top_rival_remaining')} — that's the "
            f"number a bid has to beat, not the whole table."
        )
    elif budget.get("type") == "priority":
        lines.append(
            f"WAIVERS: rolling priority, no money. My waiver position is "
            f"{budget.get('my_rank')} of {budget.get('teams_ranked')}."
        )
    else:
        lines.append(
            "WAIVERS: claim format unknown — this league was synced before budgets and "
            "waiver order were captured, so treat the tool's bid figures as percentages "
            "of a notional 100-point budget."
        )

    lines += [
        "",
        "THIS WEEK — free agents the tool ranks above my weakest starter at that "
        "position, by trend/matchup-adjusted projection:",
        "",
    ]
    for group in (data.get("this_week") or [])[:6]:
        lines.append(f"{group.get('position')}:")
        for suggestion in (group.get("suggestions") or [])[:4]:
            add = suggestion.get("add") or {}
            drop = suggestion.get("drop_candidate") or {}
            detail = (
                f"  ADD {_player_line(add, group.get('position'))} "
                f"| upgrade +{_fmt(suggestion.get('point_upgrade'))} pts"
            )
            if suggestion.get("suggested_bid") is not None:
                detail += f" | tool's bid ${suggestion['suggested_bid']}"
            else:
                detail += f" | tool's bid {suggestion.get('suggested_faab_pct')}% of budget"
            lines.append(detail)
            if drop:
                lines.append(
                    f"       would drop {drop.get('name')} (proj {_fmt(drop.get('projected_points'))})"
                )
        lines.append("")

    ros = data.get("rest_of_season") or []
    if ros:
        lines.append("REST OF SEASON — ranked by FantasyCalc market trade value instead:")
        lines.append("")
        for group in ros[:6]:
            lines.append(f"{group.get('position')}:")
            for suggestion in (group.get("suggestions") or [])[:3]:
                add = suggestion.get("add") or {}
                value = (add.get("fantasycalc") or {}).get("value")
                lines.append(
                    f"  STASH {add.get('name')} — market value {_fmt(value, 0)}, "
                    f"+{_fmt(suggestion.get('value_upgrade'), 0)} over my weakest there; "
                    f"{_matchup_line(add.get('matchup'))}"
                )
            lines.append("")
    elif not data.get("fantasycalc_available"):
        lines.append("REST OF SEASON: no market values available this sync.")
        lines.append("")

    lines.append(
        "Rank the claims I should actually put in, best first, and say what you'd bid "
        "or spend priority on. Call out any the tool has overrated — a one-week "
        "projection bump, a thin usage sample, or an add that isn't worth the drop. "
        "If a rest-of-season stash is the better use of the claim, say so."
    )
    return "\n".join(lines)


def build_trades_prompt(data: dict) -> str:
    lines = [
        f"LEAGUE: my team is {data.get('team') or 'unknown'}.",
        "",
        "The tool compared every team's starting strength and bench depth by position "
        "against the league median. Figures are summed projected points of the players "
        "filling (or backing up) that position's starting slots.",
        "",
        "WHERE I'M BELOW THE LEAGUE MEDIAN:",
    ]
    needs = data.get("needs") or []
    for need in needs:
        lines.append(
            f"  {need.get('position')}: mine {_fmt(need.get('my_starting_strength'))} "
            f"vs median {_fmt(need.get('league_median'))}"
        )
    if not needs:
        lines.append("  (none — at or above median everywhere)")

    lines += ["", "WHERE I HAVE THE LEAGUE'S DEEPEST BENCH:"]
    surpluses = data.get("surplus_to_trade") or []
    for surplus in surpluses:
        lines.append(f"  {surplus.get('position')}: bench depth {_fmt(surplus.get('my_bench_depth'))}")
    if not surpluses:
        lines.append("  (none)")

    partners = data.get("suggested_partners") or []
    lines += ["", "TEAMS THAT FIT BOTH WAYS:"]
    for partner in partners[:8]:
        gives = ", ".join(
            f"{p.get('position')} (their bench depth {_fmt(p.get('their_bench_depth'))})"
            for p in (partner.get("they_could_send") or [])
        )
        wants = ", ".join(p.get("position") or "?" for p in (partner.get("they_might_want") or []))
        lines.append(f"  {partner.get('team')}: could send me {gives or '—'}; may want my {wants or '—'}")
    if not partners:
        lines.append("  (none found)")

    lines += [
        "",
        "Which of these is worth actually messaging, and what should the opening offer "
        "be? Positional strength summed over starting slots is a blunt instrument — say "
        "where it's likely to be misleading here (one elite player masking a weak slot, "
        "depth that's only depth because of a bye, a 'need' that's really a one-week "
        "dip). If none of these are worth pursuing, say that instead.",
    ]
    return "\n".join(lines)


PROMPT_BUILDERS = {
    "start-sit": build_start_sit_prompt,
    "waivers": build_waivers_prompt,
    "trades": build_trades_prompt,
}

TOPIC_LABELS = {
    "start-sit": "Start/Sit",
    "waivers": "Waivers",
    "trades": "Trades",
}


def build_prompt(topic: str, data: dict) -> str:
    builder = PROMPT_BUILDERS.get(topic)
    if builder is None:
        raise AiAdvisorError(f"Nothing to analyse for '{topic}'.")
    if data.get("error"):
        # The recommendation modules return {"error": ...} rather than raising;
        # paying a provider to reason about an error string is pure waste.
        raise AiAdvisorError("There's no data to analyse yet — sync the league first.")
    prompt = builder(data)
    if len(prompt) > MAX_PROMPT_CHARS:
        prompt = prompt[:MAX_PROMPT_CHARS] + "\n\n[data truncated to bound the request size]"
    return prompt


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------

# Imported where they're used rather than at module scope: the app has to
# boot on a box where these aren't installed yet (an operator who pulled the
# code before re-running pip), and failing one button with a clear message
# beats failing startup with an ImportError.


def _missing_sdk(package: str) -> AiAdvisorError:
    return AiAdvisorError(
        f"The {package} library isn't installed on the server. Re-run the installer, or "
        f"have whoever manages this instance run Update App from the Admin tab."
    )


def _call_anthropic(api_key: str, model: str, prompt: str) -> str:
    try:
        import anthropic
    except ImportError as exc:
        raise _missing_sdk("anthropic") from exc

    client = anthropic.Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=1)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            # Adaptive thinking: this is a weigh-several-things-up task, and on
            # current models a thinking budget is rejected outright. Depth is
            # set by output_config.effort instead.
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError as exc:
        raise AiAdvisorError("Anthropic rejected that API key. Check it in Settings → Account.") from exc
    except anthropic.PermissionDeniedError as exc:
        raise AiAdvisorError("That Anthropic key isn't allowed to use this model.") from exc
    except anthropic.NotFoundError as exc:
        raise AiAdvisorError(
            f"Anthropic doesn't recognise the model '{model}'. Set a different one in "
            f"Settings → Account."
        ) from exc
    except anthropic.RateLimitError as exc:
        raise AiRateLimitError(
            "Anthropic is rate-limiting this key right now. Try again shortly."
        ) from exc
    except anthropic.APITimeoutError as exc:
        raise AiProviderError("Anthropic didn't answer in time. Try again.") from exc
    except anthropic.APIConnectionError as exc:
        raise AiProviderError("Couldn't reach Anthropic from this server.") from exc
    except anthropic.APIStatusError as exc:
        raise AiProviderError(f"Anthropic returned an error ({exc.status_code}).") from exc

    text = "\n\n".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        # Thinking and prose share max_tokens, so a long chain of reasoning can
        # consume the budget before any prose is written. Saying so beats
        # rendering a blank panel.
        raise AiProviderError(
            "The model used its whole response budget thinking and didn't get to an answer. "
            "Try again, or pick a lighter model in Settings → Account."
        )
    return text


def _call_openai(credential: str, model: str, prompt: str, plan_usage: bool = False) -> str:
    """One Responses API call, by API key or against a ChatGPT plan.

    The two differ in request shape, not just in who pays. Plan usage
    *requires* store=false and stream=true, and the result only counts once a
    response.completed event arrives — the SDK's get_final_response() raises
    if the stream ends without one, which is exactly the check the flow asks
    for. max_output_tokens is left off that path: the docs don't list it
    among the supported parameters, and the system prompt bounds the length
    anyway, so sending it risks a 400 to no benefit.
    """
    try:
        import openai
    except ImportError as exc:
        raise _missing_sdk("openai") from exc

    client = openai.OpenAI(api_key=credential, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=1)
    try:
        if plan_usage:
            with client.responses.stream(
                model=model,
                instructions=SYSTEM_PROMPT,
                input=prompt,
                store=False,
            ) as stream:
                response = stream.get_final_response()
        else:
            response = client.responses.create(
                model=model,
                instructions=SYSTEM_PROMPT,
                input=prompt,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
    except openai.AuthenticationError as exc:
        raise AiAdvisorError(
            "Your ChatGPT sign-in was rejected. Run the sign-in helper again and paste the "
            "new token in Settings \u2192 Account."
            if plan_usage
            else "OpenAI rejected that API key. Check it in Settings \u2192 Account."
        ) from exc
    except openai.PermissionDeniedError as exc:
        raise AiAdvisorError(
            "Your ChatGPT plan isn't authorised to run this. Plan usage needs an active Plus "
            "or Pro subscription."
            if plan_usage
            else "That OpenAI key isn't allowed to use this model."
        ) from exc
    except openai.NotFoundError as exc:
        raise AiAdvisorError(
            f"OpenAI doesn't recognise the model '{model}'. Set a different one in "
            f"Settings \u2192 Account."
        ) from exc
    except openai.RateLimitError as exc:
        raise AiRateLimitError(
            # Plan usage stops at the weekly per-app cap rather than falling
            # back to anyone's billing, so this is a wait, not a top-up.
            "You've used up this app's share of your ChatGPT plan for the week. You can raise "
            "the cap in ChatGPT \u2192 Settings \u2192 Connected apps, or wait for it to reset."
            if plan_usage
            else "OpenAI is rate-limiting this key, or the account is out of credit."
        ) from exc
    except openai.APITimeoutError as exc:
        raise AiProviderError("OpenAI didn't answer in time. Try again.") from exc
    except openai.APIConnectionError as exc:
        raise AiProviderError("Couldn't reach OpenAI from this server.") from exc
    except openai.APIStatusError as exc:
        raise AiProviderError(f"OpenAI returned an error ({exc.status_code}).") from exc
    except RuntimeError as exc:
        # get_final_response() raises this when the stream ended without a
        # response.completed event — the one case the plan-usage flow says
        # must not be treated as a success.
        raise AiProviderError("OpenAI's response was cut off before it finished. Try again.") from exc

    text = (response.output_text or "").strip()
    if not text:
        raise AiProviderError(
            "The model used its whole response budget reasoning and didn't get to an answer. "
            "Try again, or pick a lighter model in Settings \u2192 Account."
        )
    return text


_CALLERS = {ANTHROPIC: _call_anthropic, OPENAI: _call_openai}


def _credential(db: Session, user: User) -> tuple[str, bool]:
    """This account's live credential, plus whether it's a ChatGPT plan.

    Resolving the plan credential can refresh an expired access token, which
    is why this needs a session: OpenAI rotates the refresh token on every
    use, so the new pair has to be written before it's spent.
    """
    mode = auth_mode(user)
    if mode is None:
        raise AiAdvisorError(
            "No AI provider connected. Add a Claude or OpenAI key, or sign in with ChatGPT, "
            "in Settings \u2192 Account."
        )
    if mode == CHATGPT_PLAN:
        try:
            return chatgpt_oauth.access_token(db, user), True
        except chatgpt_oauth.ChatGptAuthError as exc:
            # Already phrased for a person; re-raised as our own type so the
            # HTTP layer has one exception family to catch.
            raise AiAdvisorError(str(exc)) from exc
    return user.ai_api_key, False


def generate_analysis(db: Session, user: User, topic: str, data: dict) -> dict:
    """Ask this user's own provider to reason over `data`.

    Raises AiAdvisorError for anything the user can act on — no credential,
    rate limited, provider refused — so callers can turn it straight into an
    HTTP response with a message worth reading.
    """
    provider = normalize_provider(user.ai_provider)
    credential, plan_usage = _credential(db, user)
    model = resolved_model(user) or DEFAULT_MODELS[provider]
    prompt = build_prompt(topic, data)

    check_rate_limit(user.id)
    # Counted before the call, not after: a request that times out still cost
    # the provider's compute, and counting only successes would let a
    # persistently failing loop retry without limit.
    record_call(user.id)

    if plan_usage:
        analysis = _call_openai(credential, model, prompt, plan_usage=True)
    else:
        analysis = _CALLERS[provider](credential, model, prompt)

    return {
        "topic": topic,
        "provider": provider,
        "provider_label": PROVIDER_LABELS[provider],
        "model": model,
        "analysis": analysis,
        "generated_at": datetime.datetime.utcnow(),
    }


def verify_credentials(provider: str, api_key: str, model: str, plan_usage: bool = False) -> None:
    """One cheap real call, so a typo'd key — or a sign-in that didn't
    actually grant plan usage — is caught at Save rather than discovered as a
    failed button three days later. Raises AiAdvisorError."""
    if plan_usage:
        _call_openai(api_key, model, "Reply with the single word: ready.", plan_usage=True)
        return
    caller = _CALLERS.get(provider)
    if caller is None:
        raise AiAdvisorError("Unknown provider.")
    caller(api_key, model, "Reply with the single word: ready.")
