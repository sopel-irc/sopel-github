# coding=utf8
"""
formatting.py - Sopel GitHub Module
Copyright 2015 Max Gurela
Copyright 2019 dgw

 _______ __ __   __           __
|     __|__|  |_|  |--.--.--.|  |--.
|    |  |  |   _|     |  |  ||  _  |
|_______|__|____|__|__|_____||_____|
 _______                             __   __   __
|    ___|.-----.----.--------.---.-.|  |_|  |_|__|.-----.-----.
|    ___||  _  |   _|        |  _  ||   _|   _|  ||     |  _  |
|___|    |_____|__| |__|__|__|___._||____|____|__||__|__|___  |
                                                        |_____|
"""

from __future__ import unicode_literals

import re
import requests

from sopel.formatting import color

current_row = None
current_payload = None


def fmt_url(s, row=None):
    if not row:
        row = current_row
    return color(s, fg=row[3])


def fmt_tag(s, row=None):
    if not row:
        row = current_row
    return color(s, fg=row[4])


def fmt_repo(s, row=None):
    if not row:
        row = current_row
    return color(s, fg=row[5])


def fmt_name(s, row=None):
    if not row:
        row = current_row
    return color(s, fg=row[6])


def fmt_hash(s, row=None):
    if not row:
        row = current_row
    return color(s, fg=row[7])


def fmt_branch(s, row=None):
    if not row:
        row = current_row
    return color(s, fg=row[8])


def get_distinct_commits(payload=None):
    if not payload:
        payload = current_payload
    if 'distinct_commits' in payload:
        return payload['distinct_commits']
    commits = []
    for commit in payload['commits']:
        if commit['distinct'] and len(commit['message'].strip()) > 0:
            commits.append(commit)
    return commits


def get_ref_name(payload=None):
    if not payload:
        payload = current_payload

    if 'ref_name' in payload:
        return payload['ref_name']

    payload['ref_name'] = re.sub(r'^refs/(heads|tags)/', '', payload['ref'])
    return payload['ref_name']


def get_base_ref_name(payload=None):
    if not payload:
        payload = current_payload
    return re.sub(r'^refs/(heads|tags)/', '', payload['base_ref_name'])


def get_pusher(payload=None):
    if not payload:
        payload = current_payload
    return payload['pusher']['name'] if 'pusher' in payload else 'somebody'


def get_repo_name(payload=None):
    if not payload:
        payload = current_payload
    return payload['repository']['name']


def get_after_sha(payload=None):
    if not payload:
        payload = current_payload
    return payload['after'][0:7]


def get_before_sha(payload=None):
    if not payload:
        payload = current_payload
    return payload['before'][0:7]


def get_push_summary_url(payload=None):
    if not payload:
        payload = current_payload

    repo_url = payload['repository']['url']
    if payload['created'] or re.match(r'0{40}', payload['before']):
        if len(get_distinct_commits()) < 0:
            return repo_url + "/commits/" + get_ref_name()
        else:
            return payload['compare']
    elif payload['deleted']:
        return repo_url + "/commit/" + get_before_sha()
    elif payload['forced']:
        return repo_url + "/commits/" + get_ref_name()
    elif len(get_distinct_commits()) == 1:
        return get_distinct_commits()[0]['url']
    else:
        return payload['compare']


def get_issue_type(payload=None):
    if not payload:
        payload = current_payload

    if '/pull/' in payload['issue']['html_url']:
        return "pull request"
    else:
        return "issue"


def fmt_push_summary_message(payload=None, row=None):
    if not payload:
        payload = current_payload
    if not row:
        row = current_row

    message = []
    message.append("[{}] {}".format(fmt_repo(get_repo_name()), fmt_name(get_pusher())))

    if payload['created'] or re.match(r'0{40}', payload['before']):
        if re.match(r'^refs/tags/', payload['ref']):
            message.append('tagged {} at'.format(fmt_tag(get_ref_name())))
            message.append(fmt_branch(get_base_ref_name()) if payload['base_ref'] else fmt_hash(get_after_sha()))
        else:
            message.append('created {}'.format(fmt_branch(get_ref_name())))

            if payload['base_ref']:
                message.append('from {}'.format(fmt_branch(get_base_ref_name())))
            elif len(get_distinct_commits()) == 0:
                message.append('at {}'.format(fmt_hash(get_after_sha())))

            num = len(get_distinct_commits())
            message.append('(+\002{}\017 new commit{})'.format(num, 's' if num > 1 else ''))

    elif payload['deleted'] or re.match(r'0{40}', payload['after']):
        message.append("\00304deleted\017 {} at {}".format(fmt_branch(get_ref_name()), fmt_hash(get_before_sha())))

    elif payload['forced']:
        message.append("\00304force-pushed\017 {} from {} to {}".format(
                       fmt_branch(get_ref_name()), fmt_hash(get_before_sha()), fmt_hash(get_after_sha())))

    elif len(payload['commits']) > 0 and len(get_distinct_commits()) == 0:
        if payload['base_ref']:
            message.append('merged {} into {}'.format(fmt_branch(get_base_ref_name()), fmt_branch(get_ref_name())))
        else:
            message.append('fast-forwarded {} from {} to {}'.format(
                           fmt_branch(get_ref_name()), fmt_hash(get_before_sha()), fmt_hash(get_after_sha())))

    else:
        num = len(get_distinct_commits())
        message.append("pushed \002{}\017 new commit{} to {}".format(num, 's' if num > 1 else '', fmt_branch(get_ref_name())))

    return ' '.join(message)


def fmt_commit_message(commit):
    short = commit['message'].splitlines()[0]
    short = short + '...' if short != commit['message'] else short

    author = commit['author']['name']
    sha = commit['id']

    return '{}/{} {} {}: {}'.format(fmt_repo(get_repo_name()), fmt_branch(get_ref_name()), fmt_hash(sha[0:7]), fmt_name(author), short)


def fmt_commit_comment_summary(payload=None, row=None):
    if not payload:
        payload = current_payload
    if not row:
        row = current_row

    short = payload['comment']['body'].splitlines()[0]
    short = short + '...' if short != payload['comment']['body'] else short
    return '[{}] {} commented on commit {}: {}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  fmt_hash(payload['comment']['commit_id'][0:7]),
                  short)


def fmt_issue_summary_message(payload=None):
    if not payload:
        payload = current_payload
    return '[{}] {} {} issue #{}: {}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  payload['action'],
                  payload['issue']['number'],
                  payload['issue']['title'])


def fmt_issue_assignee_message(payload=None):
    if not payload:
        payload = current_payload
    
    target = ''
    self_assign = False
    if (payload['assignee']['login'] == payload['sender']['login']):
        self_assign = True
    else:
        target = 'to ' if payload['action'] == 'assigned' else 'from '
        target = target + fmt_name(payload['assignee']['login']) 
    return '[{}] {} {}{} issue #{} {}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  'self-' if self_assign else '',
                  payload['action'],
                  payload['issue']['number'],
                  target)


def fmt_issue_label_message(payload=None):
    if not payload:
        payload = current_payload
    return '[{}] {} {} the label \'{}\' {} issue #{}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  'added' if payload['action'] == 'labeled' else 'removed',
                  payload['label']['name'],
                  'to' if payload['action'] == 'labeled' else 'from',
                  payload['issue']['number'])


def fmt_issue_comment_summary_message(payload=None):
    if not payload:
        payload = current_payload

    issue_type = get_issue_type(payload)
    short = payload['comment']['body'].splitlines()[0]
    short = short + '...' if short != payload['comment']['body'] else short
    return '[{}] {} commented on {} #{}: {}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  issue_type,
                  payload['issue']['number'],
                  short)


def fmt_pull_request_summary_message(payload=None):
    if not payload:
        payload = current_payload

    base_ref = payload['pull_request']['base']['label'].split(':')[-1]
    head_ref = payload['pull_request']['head']['label'].split(':')[-1]

    action = payload['action']
    if action == 'closed' and payload['pull_request']['merged']:
        action = 'merged'

    return '[{}] {} {} pull request #{}: {} ({}...{})'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  action,
                  payload['pull_request']['number'],
                  payload['pull_request']['title'],
                  fmt_branch(base_ref),
                  fmt_branch(head_ref))


def fmt_pull_request_review_comment_summary_message(payload=None):
    if not payload:
        payload = current_payload
    short = payload['comment']['body'].splitlines()[0]
    short = short + '...' if short != payload['comment']['body'] else short
    sha1 = payload['comment']['commit_id']
    return '[{}] {} left a file comment in pull request #{} {}: {}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  payload['pull_request']['number'],
                  fmt_hash(sha1[0:7]),
                  short)


def fmt_gollum_summary_message(payload=None):
    if not payload:
        payload = current_payload
    if len(payload['pages']) == 1:
        summary = None
        if 'summary' in payload['pages'][0]:
            summary = payload['pages'][0]['summary']

        return '[{}] {} {} wiki page {}{}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  payload['pages'][0]['action'],
                  payload['pages'][0]['title'],
                  ": " + summary if summary else '')
    elif len(payload['pages']) > 1:
        counts = {}
        for page in payload['pages']:
            # Set default value to 0 and increment 1, only incrementing if key already exists
            counts[page['action']] = counts.setdefault(page['action'], 0) + 1
        actions = []
        for action, count in counts.items():
            actions.append(action + " " + count)

        return '[{}] {} {} wiki pages'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  fmt_arr_to_sentence(actions.sort()))


def fmt_arr_to_sentence(array):
    return '{} and {}'.format(', '.join(array[:-1]), array[-1])


def fmt_watch_message(payload=None):
    if not payload:
        payload = current_payload
    return '[{}] {} starred the project!'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']))


def fmt_status_message(payload=None):
    if not payload:
        payload = current_payload
    branch = ''
    for br in payload['branches']:
        if br['commit']['sha'] == payload['sha']:
            branch = br['name']
    return '[{}/{}] {} - {} ({})'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_branch(branch),
                  payload['description'],
                  payload['target_url'],
                  payload['state'])


def shorten_url(url):
    try:
        res = requests.post('https://git.io', {'url': url})
        return res.headers['location']
    except:
        return url


def get_formatted_response(payload, row):
    global current_row, current_payload
    current_payload = payload
    current_row = row

    messages = []
    if payload['event'] == 'push':
        messages.append(fmt_push_summary_message() + " " + fmt_url(shorten_url(get_push_summary_url())))
        for commit in get_distinct_commits():
            messages.append(fmt_commit_message(commit))
    elif payload['event'] == 'commit_comment':
        messages.append(fmt_commit_comment_summary() + " " + fmt_url(shorten_url(payload['comment']['html_url'])))
    elif payload['event'] == 'pull_request':
        if re.match('((re)?open|clos)ed', payload['action']):
            messages.append(fmt_pull_request_summary_message() + " " + fmt_url(shorten_url(payload['pull_request']['html_url'])))
    elif payload['event'] == 'pull_request_review_comment' and payload['action'] == 'created':
        messages.append(fmt_pull_request_review_comment_summary_message() + " " + fmt_url(shorten_url(payload['comment']['html_url'])))
    elif payload['event'] == 'issues':
        if re.match('((re)?open|clos)ed', payload['action']):
            messages.append(fmt_issue_summary_message() + " " + fmt_url(shorten_url(payload['issue']['html_url'])))
        elif re.match('(assigned|unassigned)', payload['action']):
            messages.append(fmt_issue_assignee_message() + " " + fmt_url(shorten_url(payload['issue']['html_url'])))
        elif re.match('(labeled|unlabeled)', payload['action']):
            messages.append(fmt_issue_label_message() + " " + fmt_url(shorten_url(payload['issue']['html_url'])))
    elif payload['event'] == 'issue_comment' and payload['action'] == 'created':
        messages.append(fmt_issue_comment_summary_message() + " " + fmt_url(shorten_url(payload['comment']['html_url'])))
    elif payload['event'] == 'gollum':
        url = payload['pages'][0]['html_url'] if len(payload['pages']) else payload['repository']['url'] + '/wiki'
        messages.append(fmt_gollum_summary_message() + " " + fmt_url(shorten_url(url)))
    elif payload['event'] == 'watch':
        messages.append(fmt_watch_message())
    elif payload['event'] == 'status':
        messages.append(fmt_status_message())

    return messages
