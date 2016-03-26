from urllib2 import Request, urlopen, URLError, HTTPError
import base64, json
import datetime, time
import logging
from model import Issue
from google.appengine.ext import deferred
# Get vendored uritemplate module
from google.appengine.ext import vendor
vendor.add('lib')
import uritemplate

githubUrl = 'https://api.github.com/repos'
zenhubUrl = 'https://api.zenhub.io/p1/repositories'

def currentMillis():
    return int(round(time.time() * 1000))

def getZenhubJson(repo, url):
    if zenhubUrl not in url:
        url = zenhubUrl + url
    logging.info('zenhub GET ' + url)
    now = currentMillis()
    request = Request(url)
    request.add_header('X-Authentication-Token', repo.auth.zenhubToken)
    try:
        return json.load(urlopen(request))
    except HTTPError, err:
        logging.info('Uh oh: %s', err)

def getJson(repo, url):    
    if githubUrl not in url:
        url = githubUrl + '/' + repo.name + url
    logging.info('github GET ' + url)
    request = Request(url)
    encoded = base64.b64encode('%s:%s' % (repo.auth.githubUser, repo.auth.githubToken))
    request.add_header('Authorization', 'Basic ' + encoded)
    return json.load(urlopen(request))

def getAllPages(repo, url):
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
        page = getJson(repo, fetchUrl)
        items.extend(page)
        pageNumber += 1
        more = len(page) == pageSize
    return items


def getIssueEvents(repo, issue):
    events = getAllPages(repo, issue.github['events_url'])
    logging.info('Found %d events for #%s' % (len(events),issue.number))
    issue.github['events'] = events

def getAllIssues(repo):
    # Update the repo with content
    repo.data = getJson(repo, '')
    repo.put()

    logging.info(uritemplate.expand(repo.data['issues_url'], {}))
  
    issueUrl = uritemplate.expand(repo.data['issues_url'], {})
    issueUrl += '?state=all'
    issues = getAllPages(repo, issueUrl)
    for issueData in issues:
        issue = Issue(repo = repo.key, github = issueData, number = issueData['number'])
        getIssueEvents(repo, issue)
        issue.upsert()
    # Also load all zenhub issues. This may take a while
    getZenhubIssues(repo)

def getZenhubIssues(repo, numbers = None):
    logging.info("Getting zenhub issues from list: %s" % numbers)
    if numbers is None:
        numbers = map(lambda i: i.number, repo.issues())
        getZenhubIssues(repo, numbers)
    while numbers:
        number = numbers[0]
        issue = repo.issue(number)
        now = datetime.datetime.now()
        if not issue.zenhubUpdate or (now - issue.zenhubUpdate).total_seconds() > 60:
            zenhub = getZenhubJson(repo, '/%s/issues/%s' % (repo.data['id'], issue.number))
            if not zenhub:
                deferred.defer(getZenhubIssues, repo, numbers, _countdown=12)
                return

            zenhub['events'] = getZenhubJson(repo, '/%s/issues/%s/events' % (repo.data['id'], issue.number))
            if zenhub['events'] is None:
                deferred.defer(getZenhubIssues, repo, numbers, _countdown=12)
                return

            issue.zenhub = zenhub
            issue.zenhubUpdate = datetime.datetime.now()
            issue.upsert()
            logging.info("Updated #%s with %d zenhub events" % (number, len(zenhub['events'])))

        numbers.pop(0)
    logging.info("Complete")

def getUpdatedIssues(repo, recent):
    refresh = set()
    for page in range(0, 10):
        url = repo.data['events_url'] + '?page=%d' % page
        events = getJson(repo, url)
        for event in events:
            if event['created_at'] <= recent:
                # We are done, fetch no more
                return refresh
            elif 'issue' in event['payload']:
                number = event['payload']['issue']['number']
                logging.info('We need to refresh issue #%s' % number)
                refresh.add(number)

def first(items, matcher):
    return next((item for item in items if matcher(item)), None)

def refreshIssue(repo, issues, number):
    issue = first(issues, lambda x: x.number == number)
    if not issue:
        # Load it from scratch
        url = uritemplate.expand(repo.data['issues_url'], { 'number': number })
        issueData = getJson(repo, url)
        issue = Issue(repo = repo.key, github = issueData, number = issueData['number'])

    getIssueEvents(repo, issue)
    issue.upsert()
    issues.append(issue)

def syncIssues(repo):
    # Load all issues from store and find the most recently event update time
    issues = list(repo.issues())
    recent = None
    for issue in issues:
        for event in issue.github['events']:
            createdAt = event['created_at']
            if not recent or createdAt > recent:
                recent = createdAt

    logging.info('Looking for events that happened after %s' % recent)
    refresh = getUpdatedIssues(repo, recent)
    if not refresh:
        logging.info("No items to refresh")

    # For each issue that potentially changed, refresh it
    for number in refresh:
        refreshIssue(repo, issues, number)

    # Go get zenhub updates
    getZenhubIssues(repo, list(refresh))

    # Use the github events API to find changes after recent
    #logging.info(json.dumps(repo.data, indent=2))
