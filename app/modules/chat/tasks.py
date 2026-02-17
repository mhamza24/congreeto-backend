from app.config.celery import celery_app

@celery_app.task
def background_analysis(conversation_id: str):
    print(f"Analyzing conversation {conversation_id}")
