from urllib2 import Request, urlopen, URLError
import base64, json
import datetime, time
import logging
from model import Issue
# Get vendored uritemplate module
from google.appengine.ext import vendor
vendor.add('lib')
import uritemplate

githubUrl = 'https://api.github.com/repos'

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

def refreshIssue(repo, issues, number):
    issue = next(issue for issue in issues if issue.number == number)
    if not issue:
        # Load it from scratch
        url = uritemplate.expand(repo.data['issues_url'], { 'number': number })
        issueData = getJson(url)
        issue = Issue(repo = repo.key, github = issueData, number = issueData['number'])

    getIssueEvents(repo, issue)
    issue.upsert()
    issues.append(issue)

def syncIssues(repo):
    # Load all issues and find the most recently created event
    issues = list(repo.issues())
    recent = None
    for issue in issues:
        for event in issue.github['events']:
            createdAt = event['created_at']
            if not recent or createdAt > recent:
                recent = createdAt

    logging.info('Looking for events that happened after %s' % recent)
    refresh = getUpdatedIssues(repo, recent)

    # For each issue that potentially changed, refresh it
    for number in refresh:
        refreshIssue(repo, issues, number)

    # Use the github events API to find changes after recent
    #logging.info(json.dumps(repo.data, indent=2))
