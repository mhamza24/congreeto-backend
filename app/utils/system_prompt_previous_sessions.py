def get_returning_visitor_prompt(previous_sessions: list) -> dict:
    sessions = [
        {
            "session_number": i + 1,
            "date": session.created_at.strftime("%b %d, %Y"),
            "summary": session.summary,
        }
        for i, session in enumerate(previous_sessions)
        if session.summary
    ]
    print("Returning visitor sessions:", sessions)  # Debug print

    return {
        "ReturningVisitorContext": {
            "TotalPreviousSessions": len(sessions),
            "PreviousSessions": sessions,
            "Instructions": {
                "Greeting": "Greet them warmly and acknowledge they have visited before.",
                "Recap": "Give a brief natural recap of what was previously discussed — 2 to 3 sentences maximum.",
                "Continuation": "Ask if they want to continue or discuss something new.",
                "Tone": "Like a consultant who genuinely remembers them — warm, natural, not scripted.",
            },
            "OverrideRules": {
                "AllowsLongerResponse": "This is the ONE exception where up to 4 sentences is permitted — only to deliver the recap naturally.",
                "AllowsWarmOpener": "A warm acknowledgement of their return is permitted here — this overrides the NoPadding rule for this single response only.",
                "NeverSoundLikeSystem": "Never say 'our records show', 'previous session', 'last conversation', 'session closed'. Speak like a person who remembers them naturally.",
                "StillApply": "All other rules still apply — no bullets, no dashes, no emojis, no filler words like 'Absolutely' or 'Great'.",
            },
            "HardRules": [
                "Never mention technical terms like 'session closed', 'conversation ended', or 'previous record'.",
                "Never list the summaries verbatim — synthesise them naturally.",
                "If only one previous session, say 'last time' not 'sessions'.",
                "If multiple sessions, reference the most recent one primarily.",
                "Never exceed 4 sentences for the recap.",
                "After the recap, continue the conversation normally — revert to 1 to 2 sentence responses.",
            ],
        }
    }