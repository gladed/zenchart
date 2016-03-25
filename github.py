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

def syncIssues(repo):
    # Determine the most recently updated issue
    latest = None
    for issue in repo.issues():
        if not latest or latest < issue.github['']:
            logging.info("???")

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

    #logging.info(json.dumps(repo.data, indent=2))

