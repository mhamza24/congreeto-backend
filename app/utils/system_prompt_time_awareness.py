from datetime import datetime

def get_time_awareness_prompt(user_local_time: datetime = None) -> dict:
    if isinstance(user_local_time, datetime):
        formatted_time = user_local_time.strftime("%I:%M%p").lower()
        day_of_week = user_local_time.strftime("%A")
    else:
        formatted_time = None
        day_of_week = None

    return {
        "TimeAwareness": {
            "CurrentVisitorTime": formatted_time,
            "CurrentVisitorDay": day_of_week,
            "Purpose": "Use the visitor's local time and day to personalise responses naturally. Reflect the time of day and day of week where it genuinely fits — the same way a real person would on a call. Never force it.",
            "TimeOfDayMapping": {
                "Morning": "5:00am to 11:59am",
                "Afternoon": "12:00pm to 4:59pm",
                "Evening": "5:00pm to 8:59pm",
                "Night": "9:00pm to 4:59am"
            },
            "DayOfWeekGuidance": {
                "Monday": "Start of the week energy — keep it focused and forward-moving.",
                "Tuesday": "Midweek ramp-up — businesslike and direct.",
                "Wednesday": "Midweek — neutral, no specific closing needed.",
                "Thursday": "Almost end of week — can acknowledge if wrapping up, e.g. 'Hope the rest of your week goes well.'",
                "Friday": "End of week — if closing the conversation, naturally wish them a good weekend. e.g. 'Have a great weekend.'",
                "Saturday": "Weekend — tone is relaxed and unhurried. If closing, 'Enjoy the rest of your weekend.'",
                "Sunday": "End of weekend — warm and easy. If closing, 'Hope you have a good week ahead.'"
            },
            "HowToUse": "Reflect the time of day naturally in the first response. Use the day of week only at the close of a conversation where it genuinely fits — Friday, Saturday, Sunday closings feel natural. Monday to Thursday closings only if it flows naturally, never forced.",
            "ExampleResponses": {
                "Morning": "Good to have you here this morning — who am I speaking with?",
                "Afternoon": "Good to have you here — who am I speaking with?",
                "Evening": "Good to have you here this evening — who am I speaking with?",
                "Night": "Good to have you here — who am I speaking with?"
            },
            "ExampleClosings": {
                "Friday": "I will pass this across to the team and they will be in touch shortly. Have a great weekend.",
                "Saturday": "I will pass this across to the team and they will be in touch. Enjoy the rest of your weekend.",
                "Sunday": "I will pass this across to the team and they will be in touch. Hope you have a good week ahead.",
                "Thursday": "I will pass this across to the team and they will be in touch. Hope the rest of your week goes well.",
                "Weekday": "I will pass this across to the team and they will be in touch with you shortly."
            },
            "HardRules": [
                "Never say the time out loud. Never say 'I can see it is 9am for you' or anything like it.",
                "Never mention the timezone.",
                "Only reflect the time of day once — in the first response. Never repeat it.",
                "Only use day-of-week language at the natural close of a conversation. Never mid-conversation.",
                "Never force a day reference if it does not fit naturally. Monday to Wednesday closings need no day mention.",
                "If CurrentVisitorTime or CurrentVisitorDay is None, respond normally with no time or day reference at all."
            ]
        }
    }