"""Celery tasks for to update user progress and send reminder emails"""

import json
from logging import getLogger

import requests
from celery import task
from django.conf import settings

from ecommerce.courses.models import Course

log = getLogger(__name__)


@task(name='trigger_active_campaign_event')
def trigger_active_campaign_event(event_name, email, course_key=None):
    """Trigger active campaign event."""
    if not settings.AC_ACCOUNT_ID:
        return

    event_data = {'email': email}
    if course_key:
        course = Course.objects.get(id=course_key)
        event_data['course_name'] = course.name

    data = {
        'actid': settings.AC_ACCOUNT_ID,
        'key': settings.AC_KEY,
        'event': event_name,
        'eventdata': json.dumps(event_data),
    }

    try:
        response = requests.post(settings.AC_EVENT_URL, data=data)
        result = response.json()
        if result["success"]:
            log.info('Success! {}'.format(result['message']))
        else:
            log.info('Error: {}'.format(result['message']))
    except requests.RequestException as e:
        log.error('Request failed: {}'.format(e))
