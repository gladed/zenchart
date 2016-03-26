from urllib2 import Request, urlopen, URLError, HTTPError
import base64, json, logging, datetime, time
from google.appengine.ext import deferred
from google.appengine.ext import vendor
vendor.add('lib') # uritemplate is vendored
import uritemplate

from model import Issue

githubUrl = 'https://api.github.com/repos'
zenhubUrl = 'https://api.zenhub.io/p1/repositories'

def getZenhub(repo, url):
    if not repo.auth.zenhubToken: return
    if zenhubUrl not in url:
        url = '%s/%s%s' % (zenhubUrl, repo.data['id'], url)
    logging.info('zenhub GET ' + url)
    request = Request(url)
    request.add_header('X-Authentication-Token', repo.auth.zenhubToken)
    try:
        return json.load(urlopen(request))
    except HTTPError, err:
        logging.info('Uh oh: %s', err)

def getGithub(repo, url): 
    if githubUrl not in url:
        url = githubUrl + '/' + repo.name + url
    logging.info('github GET ' + url)
    request = Request(url)
    encoded = base64.b64encode('%s:%s' % (repo.auth.githubUser, repo.auth.githubToken))
    request.add_header('Authorization', 'Basic ' + encoded)
    return json.load(urlopen(request))

def getGithubAll(repo, url):
    pageSize = 50
    pageNumber = 0
    items = []
    more = True
    if '?' not in url: 
       url += '?'
    else:
       url += '&'
    while more:
        fetchUrl = url + 'per_page=%d&page=%d' % (pageSize, pageNumber)
        page = getGithub(repo, fetchUrl)
        items.extend(page)
        pageNumber += 1
        more = len(page) == pageSize
    return items

def getIssueEvents(repo, issue):
    """Get events for this issue from Github"""
    events = getGithubAll(repo, issue.github['events_url'])
    logging.info('Found %d events for #%s' % (len(events),issue.number))
    issue.github['events'] = events

def getAllIssues(repo):
    # Update the repo with content
    repo.data = getGithub(repo, '')
    repo.put()

    issueUrl = uritemplate.expand(repo.data['issues_url'], {})
    issueUrl += '?state=all'
    issues = getGithubAll(repo, issueUrl)
    for issueData in issues:
        issue = Issue(repo = repo.key, github = issueData, number = issueData['number'])
        getIssueEvents(repo, issue)
        issue.upsert()

    # Also load all zenhub issues. This may take a while
    getZenhubIssues(repo.key)

def getZenhubIssues(repoKey, keys = None):
    repo = repoKey.get()   
    if not repo or not repo.auth.zenhubToken: return
    if keys is None:
        keys = map(lambda i: i.key, repo.issues())
    logging.info("Getting zenhub issues from list (%s)" % len(keys))
    while keys:
        key = keys[0]
        issue = key.get()
        if getZenhubIssue(repo, issue):
            keys.pop(0)
        else:
            logging.info("Deferring at %s" % issue.number)
            deferred.defer(getZenhubIssues, repoKey, keys, _countdown=20)
            break
    return True

def getZenhubIssue(repo, issue):
    now = datetime.datetime.now()
    if hasattr(issue, 'zenhubUpdate') and issue.zenhubUpdate and (now - issue.zenhubUpdate).total_seconds() < 60:
        return True
    zenhub = getZenhub(repo, '/issues/%s' % issue.number)
    if not zenhub: return False
    zenhub['events'] = getZenhub(repo, '/issues/%s/events' % issue.number)
    if zenhub['events'] is None: return False
    issue.zenhub = zenhub
    issue.zenhubUpdate = now
    issue.upsert()
    logging.info("Updated #%s with %d zenhub events" % (issue.number, len(zenhub['events'])))
    return True

def getUpdatedIssues(repo, recent):
    """Return issue numbers for issues updated in github since 'recent'"""
    refresh = set()
    latestEventTime = None
    for page in range(0, 10):
        url = repo.data['events_url'] + '?page=%d' % page
        events = getGithub(repo, url)        
        for event in events:
            latestEventTime = max(latestEventTime, event['created_at'])
            if event['created_at'] <= recent:
                # We are done, fetch no more
                return refresh, latestEventTime
            elif 'issue' in event['payload']:
                number = event['payload']['issue']['number']
                refresh.add(number)
    return refresh, latestEventTime

def findIssue(issues, number):
    """Return the first issue in issues with the same number"""
    for issue in issues:
        if issue.number == number:
            return issue

def syncIssues(repo):
    # Load all issues from store and find the most recent update time
    recent = None
    for issue in repo.issues():
        logging.info("Comparing %s" % issue.githubUpdate)
        recent = max(recent, issue.githubUpdate)

    logging.info("Getting updated issues since %s" % recent)
    toRefresh, recent = getUpdatedIssues(repo, recent)
    if not toRefresh:
        logging.info("No items to refresh")
        return

    # For each issue that potentially changed, refresh it
    keysToRefresh = []
    for number in toRefresh:
        # if the repo suddenly disappears, quit
        if not repo.key.get(): return
        issue = repo.issue(number)
        if not issue:
            issue = Issue(repo = repo.key, number = number)
        url = uritemplate.expand(repo.data['issues_url'], { 'number': number })
        issue.github = getGithub(repo, url) 
        getIssueEvents(repo, issue)
        issue.githubUpdate = recent
        logging.info("Upserting issue %s" % issue.number)
        issue.upsert()
        keysToRefresh.append(issue.key)

    # Go get zenhub updates (separately so it can be metered safely)
    getZenhubIssues(repo.key, keysToRefresh)
