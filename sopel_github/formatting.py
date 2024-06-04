"""
formatting.py - Part of Sopel GitHub Plugin

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

from __future__ import annotations

import re
import textwrap

from sopel.formatting import color
from sopel import tools

try:
    import emoji
except ImportError:
    emojize = lambda text: text
else:
    emojize = lambda text: emoji.emojize(text, language='alias')

current_row = None
current_payload = None

LOGGER = tools.get_logger('github')

MARKDOWN_HEADING = re.compile(r'#+\s+')


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


def fmt_short_comment_body(body):
    if body is None or body.strip() == '':
        return '(empty comment)'

    lines = [
        line.strip()
        for line in body.splitlines()
        if line
        and line[0] != '>'  # Markdown quote
        and not MARKDOWN_HEADING.match(line)  # Markdown heading
        and not line.startswith('<!-')  # commented out HTML-style
    ]
    # if there's nothing left, the comment is "empty"
    if not lines:
        return '(no body text)'

    # abbreviate commit hashes in the text
    line = re.sub(r'[a-f0-9]{40}', lambda m: m.group(0)[:7], lines[0])
    # wrap text to get a line of at most 250 chars
    short = textwrap.wrap(line, 250)[0]
    # add continuation marker if needed
    if len(lines) > 1 or short != line:
        short += ' […]'

    return short


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
    return re.sub(r'^refs/(heads|tags)/', '', payload['ref'])


def get_base_ref_name(payload=None):
    if not payload:
        payload = current_payload
    return re.sub(r'^refs/(heads|tags)/', '', payload['base_ref'])


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

    is_pr = ('pull_request' in payload or ('issue' in payload and '/pull/' in payload['issue']['html_url']))

    if is_pr:
        return "pull request"
    else:
        return "issue"


def get_issue_or_pr_number(payload=None):
    if not payload:
        payload = current_payload

    try:
        number = payload['issue']['number']
    except KeyError:
        number = payload['pull_request']['number']

    return number


def get_issue_or_pr_title(payload=None):
    if not payload:
        payload = current_payload

    try:
        title = payload['issue']['title']
    except KeyError:
        title = payload['pull_request']['title']

    return title


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
    short = short + '…' if short != commit['message'] else short

    author = commit['author']['name']
    sha = commit['id']

    return '{}/{} {} {}: {}'.format(fmt_repo(get_repo_name()), fmt_branch(get_ref_name()), fmt_hash(sha[0:7]), fmt_name(author), short)


def fmt_commit_comment_summary(payload=None, row=None):
    if not payload:
        payload = current_payload
    if not row:
        row = current_row

    short = fmt_short_comment_body(payload['comment']['body'])
    return '[{}] {} commented on commit {}: {}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  fmt_hash(payload['comment']['commit_id'][0:7]),
                  emojize(short))


def fmt_issue_summary_message(payload=None):
    if not payload:
        payload = current_payload
    return '[{}] {} {} issue #{}: {}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  payload['action'],
                  payload['issue']['number'],
                  emojize(payload['issue']['title']))


def fmt_issue_incoming_transfer_message(payload=None):
    if not payload:
        payload = current_payload
    # GitHub unfortunately doesn't seem to include any info about the user who
    # initiated the issue transfer, only the original author/creator.
    return '[{}] {}#{} by {} was transferred to issue #{}: {}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_repo(payload['changes']['old_repository']['full_name']),
                  payload['changes']['old_issue']['number'],
                  fmt_name(payload['issue']['user']['login']),
                  payload['issue']['number'],
                  emojize(payload['issue']['title']))


def fmt_issue_outgoing_transfer_message(payload=None):
    if not payload:
        payload = current_payload
    # For "transferred" events (sent for the source repo only), GitHub DOES set
    # the "sender" info to the user who initiated the transfer, unlike for
    # inbound transfer hooks (which just look like any other "opened" event
    # except for the addition of a "changes" object).
    return '[{}] {} transferred issue #{} by {} to {}#{}: {}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  payload['issue']['number'],
                  fmt_name(payload['issue']['user']['login']),
                  fmt_repo(payload['changes']['new_repository']['full_name']),
                  payload['changes']['new_issue']['number'],
                  emojize(payload['issue']['title']))


def fmt_issue_title_edit(payload=None):
    if not payload:
        payload = current_payload
    return '[{}] {} retitled issue #{}: "{}" ➜ "{}"'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  payload['issue']['number'],
                  emojize(payload['changes']['title']['from']),
                  emojize(payload['issue']['title']))


def fmt_issue_assignee_message(payload=None):
    if not payload:
        payload = current_payload

    target = ''
    assignee = payload['assignee']['login']
    self_assign = False

    if assignee == payload['sender']['login']:
        self_assign = True
    else:
        prep = 'to' if payload['action'] == 'assigned' else 'from'
        target = ' {} {}'.format(prep, fmt_name(assignee))

    return '[{}] {} {}{} {} #{}{} ({})'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  'self-' if self_assign else '',
                  payload['action'],
                  get_issue_type(payload),
                  get_issue_or_pr_number(payload),
                  target,
                  get_issue_or_pr_title(payload))


def fmt_issue_label_message(payload=None):
    if not payload:
        payload = current_payload
    return '[{}] {} {} the label \'{}\' {} {} #{} ({})'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  'added' if payload['action'] == 'labeled' else 'removed',
                  payload['label']['name'],
                  'to' if payload['action'] == 'labeled' else 'from',
                  get_issue_type(payload),
                  get_issue_or_pr_number(payload),
                  get_issue_or_pr_title(payload))


def fmt_issue_milestone_message(payload=None):
    if not payload:
        payload = current_payload

    added = payload['action'] == 'milestoned'

    return '[{}] {} {} {} #{} ({}) {} the {} milestone'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  'added' if added else 'removed',
                  get_issue_type(payload),
                  get_issue_or_pr_number(payload),
                  get_issue_or_pr_title(payload),
                  'to' if added else 'from',
                  payload['milestone']['title'])


def fmt_issue_comment_summary_message(payload=None):
    if not payload:
        payload = current_payload

    issue_type = get_issue_type(payload)
    short = fmt_short_comment_body(payload['comment']['body'])
    return '[{}] {} commented on {} #{}: {}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  issue_type,
                  payload['issue']['number'],
                  emojize(short))


def fmt_pull_request_summary_message(payload=None):
    if not payload:
        payload = current_payload

    action = payload['action']
    if action == 'closed' and payload['pull_request']['merged']:
        action = 'merged'
    elif action == 'opened' and payload['pull_request'].get('draft', False):
        action = 'drafted'
    elif action == 'ready_for_review':
        action = 'readied'
    elif action == 'converted_to_draft':
        action = 'un-readied'

    actor = payload['sender']['login']
    author = payload['pull_request']['user']['login']
    maybe_possessive = ''
    if action == 'merged' and actor != author:
        maybe_possessive = '%s\'s ' % fmt_name(author)

    base = fmt_branch(payload['pull_request']['base']['ref'])
    head = fmt_branch(payload['pull_request']['head']['ref'])
    base_repo = payload['pull_request']['base']['user']['login']
    head_repo = payload['pull_request']['head']['user']['login']
    if base_repo != head_repo:
        base = "{}:{}".format(fmt_name(base_repo), base)
        head = "{}:{}".format(fmt_name(head_repo), head)

    return '[{}] {} {} {}pull request #{}: {} ({}...{})'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(actor),
                  action,
                  maybe_possessive,
                  payload['pull_request']['number'],
                  emojize(payload['pull_request']['title']),
                  base,
                  head)


def fmt_pull_request_title_edit(payload=None):
    if not payload:
        payload = current_payload
    return '[{}] {} retitled PR #{}: "{}" ➜ "{}"'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  payload['pull_request']['number'],
                  emojize(payload['changes']['title']['from']),
                  emojize(payload['pull_request']['title']))


def fmt_pull_request_review_summary_message(payload=None):
    if not payload:
        payload = current_payload

    action = payload['review']['state']
    if action == 'commented':
        action = 'left a review on'
    elif action == 'changes_requested':
        action = 'requested changes on'

    body = payload['review']['body']
    short = ''
    if body:
        short = fmt_short_comment_body(body)
        short = ': ' + short

    return '[{}] {} {} pull request #{}{}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  action,
                  payload['pull_request']['number'],
                  emojize(short))


def fmt_pull_request_review_dismissal_message(payload=None):
    if not payload:
        payload = current_payload

    if payload['sender']['login'] == payload['review']['user']['login']:
        whose = 'their'
    else:
        whose = fmt_name(payload['review']['user']['login']) + '\'s'

    return '[{}] {} dismissed {} review on pull request #{}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  whose,
                  payload['pull_request']['number'])


def fmt_pull_request_review_comment_summary_message(payload=None):
    if not payload:
        payload = current_payload
    short = fmt_short_comment_body(payload['comment']['body'])
    sha1 = payload['comment']['commit_id']
    return '[{}] {} left a file comment in pull request #{} {}: {}'.format(
                  fmt_repo(payload['repository']['name']),
                  fmt_name(payload['sender']['login']),
                  payload['pull_request']['number'],
                  fmt_hash(sha1[0:7]),
                  emojize(short))


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


def fmt_arr_to_sentence(seq):
    if len(seq) <= 2:
        return ' and '.join(seq)
    else:
        return '{}, and {}'.format(', '.join(seq[:-1]), seq[-1])


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


def fmt_release_message(payload=None):
    if not payload:
        payload = current_payload

    return '[{}] {} released {}{}'.format(
        fmt_repo(payload['repository']['name']),
        fmt_name(payload['release']['author']['login']),
        payload['release']['name'] or payload['release']['tag_name'],
        ' (prerelease)' if payload['release']['prerelease'] else '')


def get_formatted_response(payload, row):
    global current_row, current_payload
    current_payload = payload
    current_row = row

    messages = []
    if payload['event'] == 'push':
        messages.append(fmt_push_summary_message() + " " + fmt_url(get_push_summary_url()))
        for commit in get_distinct_commits():
            messages.append(fmt_commit_message(commit))
    elif payload['event'] == 'commit_comment':
        messages.append(fmt_commit_comment_summary() + " " + fmt_url(payload['comment']['html_url']))
    elif payload['event'] == 'pull_request':
        if re.match('((re)?open|clos)ed', payload['action']) or payload['action'] in ['ready_for_review', 'converted_to_draft']:
            messages.append(fmt_pull_request_summary_message() + " " + fmt_url(payload['pull_request']['html_url']))
        elif payload['action'] == 'edited':
            if 'changes' in payload:
                if 'title' in payload['changes']:
                    messages.append(fmt_pull_request_title_edit() + " " + fmt_url(payload['pull_request']['html_url']))
        elif re.match('(assigned|unassigned)', payload['action']):
            messages.append(fmt_issue_assignee_message() + " " + fmt_url(payload['pull_request']['html_url']))
        elif re.match('(labeled|unlabeled)', payload['action']):
            if payload.get('label', None):
                # If a label is deleted, for example, we'll get a webhook payload with no details about the removed label.
                # We skip those; there's no reason to emit action messages to IRC with "unknown label" placeholders.
                messages.append(fmt_issue_label_message() + " " + fmt_url(payload['pull_request']['html_url']))
    elif payload['event'] == 'pull_request_review':
        if payload['action'] == 'submitted' and payload['review']['state'] in ['approved', 'changes_requested', 'commented']:
            if payload['review']['state'] == 'commented' and payload['review']['body'] is None:
                # Probably an empty "review" fired by a pull_request_review_comment reply, which we'll get in a separate hook delivery.
                # Wish GitHub didn't fire both events, but they do, even though it makes no sense.
                # Either way, an empty review must be accompanied by comments, which will get handled when their hook(s) fire(s).
                pass
            else:
                messages.append(fmt_pull_request_review_summary_message() + " " + fmt_url(payload['review']['html_url']))
        elif payload['action'] == 'dismissed':
            messages.append(fmt_pull_request_review_dismissal_message() + " " + fmt_url(payload['review']['html_url']))
    elif payload['event'] == 'pull_request_review_comment' and payload['action'] == 'created':
        messages.append(fmt_pull_request_review_comment_summary_message() + " " + fmt_url(payload['comment']['html_url']))
    elif payload['event'] == 'issues':
        if re.match('((re)?open|clos)ed', payload['action']):
            if 'changes' in payload and all(k in payload['changes'] for k in ['old_repository', 'old_issue']):
                messages.append(fmt_issue_incoming_transfer_message() + " " + fmt_url(payload['issue']['html_url']))
            else:
                messages.append(fmt_issue_summary_message() + " " + fmt_url(payload['issue']['html_url']))
        elif re.match('(assigned|unassigned)', payload['action']):
            messages.append(fmt_issue_assignee_message() + " " + fmt_url(payload['issue']['html_url']))
        elif re.match('(labeled|unlabeled)', payload['action']):
            if payload.get('label', None):
                # If a label is deleted, for example, we'll get a webhook payload with no details about the removed label.
                # We skip those; there's no reason to emit action messages to IRC with "unknown label" placeholders.
                messages.append(fmt_issue_label_message() + " " + fmt_url(payload['issue']['html_url']))
        elif re.match('(milestoned|demilestoned)', payload['action']):
            messages.append(fmt_issue_milestone_message() + " " + fmt_url(payload['issue']['html_url']))
        elif payload['action'] == 'edited':
            if 'changes' in payload:
                if 'title' in payload['changes']:
                    messages.append(fmt_issue_title_edit() + " " + fmt_url(payload['issue']['html_url']))
        elif payload['action'] == 'transferred':
            messages.append(fmt_issue_outgoing_transfer_message() + " " + fmt_url(payload['changes']['new_issue']['html_url']))
    elif payload['event'] == 'issue_comment' and payload['action'] == 'created':
        messages.append(fmt_issue_comment_summary_message() + " " + fmt_url(payload['comment']['html_url']))
    elif payload['event'] == 'gollum':
        url = payload['pages'][0]['html_url'] if len(payload['pages']) else payload['repository']['url'] + '/wiki'
        messages.append(fmt_gollum_summary_message() + " " + fmt_url(url))
    elif payload['event'] == 'watch':
        messages.append(fmt_watch_message())
    elif payload['event'] == 'status':
        messages.append(fmt_status_message())
    elif payload['event'] == 'release':
        if payload['action'] == 'published':
            # Currently the only possible action, but other events might eventually fire webhooks too
            messages.append(fmt_release_message() + " " + fmt_url(payload['release']['html_url']))

    return messages
