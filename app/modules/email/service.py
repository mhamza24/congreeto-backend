from fastapi_mail import FastMail, MessageSchema, MessageType
from app.config.email import conf as email_config

fm = FastMail(email_config)


async def test(recipients_list: list[str], username: str = "MHK"):
    message = MessageSchema(
        subject="Welcome to Our App!",
        recipients=recipients_list,
        body=f"<h1>Welcome, {username}!</h1><p>Thanks for signing up.</p>",
        subtype=MessageType.html
    )
    await fm.send_message(message)
