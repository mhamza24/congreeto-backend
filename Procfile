web: uvicorn main:app --host 0.0.0.0 --port $PORT
worker: celery -A app.config.celery_worker.celery_app worker --pool=solo -Q analysis -l info