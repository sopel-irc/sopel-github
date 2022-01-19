# coding=utf8
"""
webhook.py - Sopel GitHub Module
Copyright 2015 Max Gurela
Copyright 2019 dgw

 _______ __ __   __           __
|     __|__|  |_|  |--.--.--.|  |--.
|    |  |  |   _|     |  |  ||  _  |
|_______|__|____|__|__|_____||_____|
 ________         __     __                 __
|  |  |  |.-----.|  |--.|  |--.-----.-----.|  |--.-----.
|  |  |  ||  -__||  _  ||     |  _  |  _  ||    <|__ --|
|________||_____||_____||__|__|_____|_____||__|__|_____|

"""

from __future__ import unicode_literals

from sopel import tools
from sopel.formatting import bold, color
from sopel.tools.time import get_timezone, format_time

from .formatting import get_formatted_response
from .formatting import fmt_repo
from .formatting import fmt_name

from threading import Thread
import bottle
import hashlib
import hmac
import json
import requests

LOGGER = tools.get_logger('github')

# Because I'm a horrible person
sopel_instance = None

def setup_webhook(sopel):
    global sopel_instance
    sopel_instance = sopel
    host = sopel.config.github.webhook_host
    port = sopel.config.github.webhook_port

    base = StoppableWSGIRefServer(host=host, port=port)
    server = Thread(target=bottle.run, kwargs={'server': base})
    server.setDaemon(True)
    server.start()
    sopel.memory['gh_webhook_server'] = base
    sopel.memory['gh_webhook_thread'] = server

    conn = sopel.db.connect()
    c = conn.cursor()

    try:
        c.execute('SELECT * FROM gh_hooks')
    except Exception:
        create_table(sopel, c)
        conn.commit()
    conn.close()


def create_table(bot, c):
    primary_key = '(channel, repo_name)'

    c.execute('''CREATE TABLE IF NOT EXISTS gh_hooks (
        channel TEXT,
        repo_name TEXT,
        enabled BOOL DEFAULT 1,
        url_color TINYINT DEFAULT 2,
        tag_color TINYINT DEFAULT 6,
        repo_color TINYINT DEFAULT 13,
        name_color TINYINT DEFAULT 15,
        hash_color TINYINT DEFAULT 14,
        branch_color TINYINT DEFAULT 6,
        PRIMARY KEY {0}
        )'''.format(primary_key))


def shutdown_webhook(sopel):
    global sopel_instance
    sopel_instance = None
    if 'gh_webhook_server' in sopel.memory:
        print('Stopping webhook server')
        sopel.memory['gh_webhook_server'].stop()
        sopel.memory['gh_webhook_thread'].join()
        print('GitHub webhook shutdown complete')


class StoppableWSGIRefServer(bottle.ServerAdapter):
    server = None

    def run(self, handler):
        from wsgiref.simple_server import make_server, WSGIRequestHandler
        if self.quiet:
            class QuietHandler(WSGIRequestHandler):
                def log_request(*args, **kw):
                    pass
            self.options['handler_class'] = QuietHandler
        self.server = make_server(self.host, self.port, handler, **self.options)
        self.server.serve_forever()

    def stop(self):
        self.server.shutdown()


def get_targets(repo):
    conn = sopel_instance.db.connect()
    c = conn.cursor()
    c.execute('SELECT * FROM gh_hooks WHERE repo_name = ? AND enabled = 1', (repo.lower(), ))
    return c.fetchall()


def process_payload(payload, targets):
    if payload['event'] == 'ping':
        for row in targets:
            sopel_instance.say('[{}] {}: {} (Your webhook is now enabled)'.format(
                          fmt_repo(payload['repository']['name'], row),
                          fmt_name(payload['sender']['login'], row),
                          payload['zen']), row[0])
        return

    for row in targets:
        messages = get_formatted_response(payload, row)
        # Write the formatted message(s) to the channel
        for message in messages:
            sopel_instance.say(message, row[0])


def debug_log_request(request_headers, request_body):
    LOGGER.debug('Headers: {}'.format(dict([(k, request_headers[k]) for k in request_headers])))
    LOGGER.debug('Request: {}'.format(request_body.decode('utf-8')))


def abort_request(status_code=400, response_message=None):
    if sopel_instance.config.github.debug_mode:
        LOGGER.warning('`debug_mode = True`; allowing unverified request...')
        return None
    return bottle.abort(status_code, response_message)


def verify_request():
    request_headers = bottle.request.headers
    request_body = bottle.request.body.read()

    if not request_headers.get('X-Hub-Signature'):
        msg = 'Request is missing a hash signature.'
        LOGGER.error(msg)
        debug_log_request(request_headers, request_body)
        return abort_request(401, msg)  # 401 Unauthorized; missing required header

    digest_name, payload_signature = request_headers.get('X-Hub-Signature').split('=')
    # Currently, GitHub only uses 'sha1'; log a warning if a different digest is
    # specified by the server. GitHub may have started using a new digest and
    # this should be confirmed.
    if digest_name != 'sha1':
        LOGGER.warning('Unexpected signature digest: {}'.format(digest_name))
        debug_log_request(request_headers, request_body)

    try:
        digest_mod = getattr(hashlib, digest_name)
    except AttributeError:
        # The previous digest check does not require a 'sha1' digest, but simply
        # warns when an unexpected digest is specified. The function will
        # attempt to find the digest specified in the signature, but if it is
        # not currently supported by Python's `hashlib`, an error will be logged
        # and returned.
        msg = 'Unsupported signature digest: {}'.format(digest_name)
        LOGGER.error(msg)
        debug_log_request(request_headers, request_body)
        return abort_request(501, msg)  # 501 Not Implemented; server does not support the functionality required to fulfill the request

    secret = sopel_instance.config.github.webhook_secret
    hash_ = hmac.new(secret.encode('utf-8') if secret else None, msg=request_body, digestmod=digest_mod)
    expected_signature = hash_.hexdigest()
    if payload_signature != expected_signature:
        msg = 'Request signature mismatch.'
        LOGGER.error(msg)
        debug_log_request(request_headers, request_body)
        return abort_request(403, msg)  # 403 Forbidden; server understood the request but refuses to authorize it


@bottle.get("/webhook")
def show_hook_info():
    if sopel_instance.config.github.debug_mode:
        return 'Listening for webhook connections!'
    # bottle.abort() == raise HTTPError(); manually raising HTTPError allows passing extra headers
    raise bottle.HTTPError(405, Allow='POST')  # 405 Method Not Allowed; this route is only useful for testing.


@bottle.post("/webhook")
def webhook():
    if sopel_instance.config.github.webhook_secret:
        verify_request()  # function will automatically abort this webhook if verification fails
        # If you made it here, then validation was successful.

    event = bottle.request.headers.get('X-GitHub-Event') or 'ping'

    try:
        payload = bottle.request.json
    except:
        return bottle.abort(400, 'Something went wrong!')

    payload['event'] = bottle.request.headers.get('X-GitHub-Event') or 'ping'
    targets = get_targets(payload['repository']['full_name'])

    # process hook payload in background
    payload_handler = Thread(target=process_payload, args=(payload, targets))
    payload_handler.start()

    # send HTTP response ASAP, hopefully within GitHub's very short timeout
    return '{"channels":' + json.dumps([target[0] for target in targets]) + '}'


@bottle.get('/auth')
def handle_auth_response():
    code = bottle.request.query.code
    state = bottle.request.query.state

    repo = state.split(':')[0]
    channel = state.split(':')[1]

    data = {'client_id': sopel_instance.config.github.client_id,
            'client_secret': sopel_instance.config.github.client_secret,
            'code': code}
    raw = requests.post('https://github.com/login/oauth/access_token', data=data, headers={'Accept': 'application/json'})
    try:
        res = json.loads(raw.text)

        if 'error' in res:
            raise ValueError('{err}: {desc}'.format(err=res['error'], desc=res['error_description']))
        if 'scope' not in res:
            raise ValueError('You\'ve already completed authorization on this repo')
        if 'write:repo_hook' not in res['scope']:
            raise ValueError('You didn\'t allow read/write on repo hooks!')

        access_token = res['access_token']

        data = {
            "name": "web",
            "active": True,
            "events": ["*"],
            "config": {
                "url": sopel_instance.config.github.external_url,
                "content_type": "json"
            }
        }

        if sopel_instance.config.github.webhook_secret:
            data['config']['secret'] = sopel_instance.config.github.webhook_secret

        raw = requests.post('https://api.github.com/repos/{}/hooks?access_token={}'.format(repo, access_token), data=json.dumps(data))
        res = json.loads(raw.text)

        if 'ping_url' not in res:
            if 'errors' in res:
                raise ValueError(', '.join([error['message'] for error in res['errors']]))
            else:
                raise ValueError('Webhook creation failed, try again.')

        raw = requests.get(res['ping_url'] + '?access_token={}'.format(access_token))

        title = 'Done!'
        header = 'Webhook setup complete!'
        body = 'That was simple, right?! You should be seeing a completion message in {} any second now'.format(channel)
        flair = 'There\'s no way it was that easy… things are never this easy…'
    except Exception as e:
        title = 'Error!'
        header = 'Webhook setup failed!'
        body = 'Please try using the link in {} again, something went wrong!'.format(channel)
        flair = str(e)

    page = '''
<!DOCTYPE html>
<html>
  <head>
    <title>{title}</title>
    <style>
      body {{
        width: 35em;
        margin: 0 auto;
        font-family: Tahoma, Verdana, Arial, sans-serif;
      }}
    </style>
  </head>
  <body>
    <h1>{header}</h1>
    <p>{body}</p>
    <small><em>{flair}</em></small>
  </body>
</html>
    '''

    return page.format(title=title, header=header, body=body, flair=flair)
