import logging
logger = logging.getLogger(__name__)
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
        "IMMEDIATE_ACTION_REQUIRED": {
            "Instruction": "EXECUTE THIS BEFORE ANYTHING ELSE IN YOUR RESPONSE. This visitor has been here before. You must acknowledge their return and recap their previous session naturally in your reply. This overrides all other rules except formatting.",
            "TotalPreviousSessions": len(sessions),
            "PreviousSessions": sessions,
            "HowToDeliver": "Speak like a consultant who genuinely remembers them. Weave the recap into your reply naturally. Do not sound like a system reading a log.",
            "ExampleTone": "Good to have you back. Last time we were looking at how Veloce could work for your business and you had shared your details with the team. Anything you wanted to follow up on, or shall we pick up from there?",
            "HardRules": [
                "Never say 'previous session', 'session closed', 'our records show', or 'last conversation'.",
                "Never list the summary verbatim — synthesise it into natural speech.",
                "If one previous session, say 'last time' not 'last session'.",
                "Keep the recap to 2 sentences maximum then ask one forward moving question.",
                "After this response revert to all normal conversation rules.",
            ],
        }
    }