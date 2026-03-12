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

    return {
        "ReturningVisitorContext": {
            "TotalPreviousSessions": len(sessions),
            "PreviousSessions": sessions,
            "Instructions": {
                "Greeting": "Greet them warmly and acknowledge they have visited before.",
                "Recap": "Give a brief natural recap of what was previously discussed — 2 to 3 sentences maximum.",
                "Continuation": "Ask if they want to continue from where they left off or discuss something new.",
                "Tone": "Keep it natural and conversational — like a person who remembers them, not a system reading a log.",
            },
            "HardRules": [
                "Never mention technical terms like 'session closed', 'conversation ended', or 'previous record'.",
                "Never list the summaries verbatim — synthesise them naturally into the greeting.",
                "If there is only one previous session, do not say 'sessions' — say 'last time'.",
                "If there are multiple sessions, reference the most recent one primarily.",
                "Never make the recap longer than 2 to 3 sentences.",
            ],
        }
    }