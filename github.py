import webapp2, sys, urllib, urlparse, random
import base64, json, logging, datetime, time
from urllib2 import Request, urlopen, HTTPError
from google.appengine.ext import deferred
from google.appengine.ext import vendor
vendor.add('lib') # uritemplate is vendored
import uritemplate
from model import Issue, Repo
import zenhub

githubUrl = 'https://api.github.com'

class Github:
    def __init__(self, me):
        self.me = me

    def get(self, url):
        logging.info('github GET ' + url)
        request = Request(url)
        # Add credentials as we have them
        if 'paToken' in self.me:
            #logging.info("Adding personal access token from session")
            encoded = base64.b64encode(':%s' % self.me['paToken'])
            request.add_header('Authorization', 'Basic ' + encoded)
        elif 'aToken' in self.me:
            request.add_header('Authorization', 'token ' + self.me['aToken'])
        return json.load(urlopen(request))

    def getAll(self, url):
        """Fetches pages of items"""
        pageSize = 50
        pageNumber = 0
        items = []
        more = True
        if '?' not in url: 
           url += '?'
        else:
           url += '&'
        while more:
            page = self.get(url + 'per_page=%d&page=%d' % (pageSize, pageNumber))
            items.extend(page)
            pageNumber += 1
            more = len(page) == pageSize
        return items

    def repos(self):
        repos = self.get(self.me['repos_url'])
        subs = self.get(self.me['subscriptions_url'])
        repoNames = map(lambda r: r['full_name'], repos)
        for sub in subs:
            if sub['full_name'] not in repoNames:
                repos.append(sub)
        return repos

    def repo(self, name):
        return self.get(githubUrl + '/repos/' + name)

    def user(self):
        """Get user info from github and store it in the session"""
        return self.get('%s/user' % githubUrl)

    def issue(self, repo, number, oldData):
        """Return github issue and event data"""
        url = uritemplate.expand(repo.data['issues_url'], { 'number': number })
        issue = self.get(url)
        # TODO: only get events up to the most recent in oldData?
        issue['events'] = self.getAll(issue['events_url'])
        logging.info('Found %d events for #%s' % (len(issue['events']), number))
        return issue

    def syncIssues(self, repoKey):
        repo = repoKey.get()

        issues = repo.issues()
        if issues:
            issueTime = max(map(lambda x: x.githubUpdate, issues))
        else:
            issueTime = None
    
        logging.info("Getting updated issues since %s" % issueTime)
        newNumbers, updateTime = self.newIssueNumbers(repo, issueTime)

        # Refresh each new issue
        for number in newNumbers:
            # if the repo suddenly disappears, quit
            if not repoKey.get(): return
            issue = repo.issue(number)
            if not issue:
                issue = Issue(repo = repo.key, number = number)
            issue.github = self.issue(repo, number, issue.github)
            issue.githubUpdate = updateTime
            issue.zenhubUpdate = None  # mark for Zenhub update
            logging.info("Upserting issue %s" % issue.number)
            issue.upsert()

        # After a github sync, start a zenhub sync
        zenhub.syncIssues(repo.key)
    
    def newIssueNumbers(self, repo, until):
        """Return issues that changed after issueTime, along with most recent update time"""
        numbers = set()
        latestTime = None
        for page in range(0, 10):
            url = repo.data['events_url'] + '?page=%d' % page
            for event in self.get(url):
                latestTime = max(latestTime, event['created_at'])
                if event['created_at'] <= until:
                    # We are done, fetch no more
                    return numbers, latestTime
                elif 'issue' in event['payload']:
                    numbers.add(event['payload']['issue']['number'])
        return list(numbers), latestTime

def syncIssues(user, repoKey):
    try:
        Github(user).syncIssues(repoKey)
    except:
        logging.exception('Failed to sync Github issues')
