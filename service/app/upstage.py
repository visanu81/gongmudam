"""Explicit Upstage endpoint and preset; no secrets or automatic model calls."""
import re

BASE_URL = 'https://api.upstage.ai/v1'


def profile():
    return dict(provider='openai_compatible', base_url=BASE_URL, model='solar-pro4',
                api_key='', api_key_env='UPSTAGE_API_KEY', temperature=0.1,
                max_tokens=1500, timeout=60, extra_body={'reasoning_effort':'none'})


def matches(value):
    return (value.get('provider') == 'openai_compatible'
            and value.get('base_url', '').rstrip('/') == BASE_URL
            and isinstance(value.get('model'), str)
            and re.fullmatch(r'solar-(?:pro4|mini4)(?:-\d{6})?', value['model']) is not None)


def same_model(expected, actual):
    return isinstance(actual, str) and (expected == actual or
        (expected in ('solar-pro4','solar-mini4') and re.fullmatch(re.escape(expected)+r'-\d{6}', actual) is not None))
